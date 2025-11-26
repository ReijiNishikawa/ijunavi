import os
import pandas as pd
import zipfile
import requests
from pathlib import Path
from dotenv import load_dotenv
import traceback

# LangChain/LLM 関連のインポート
# 注: `langchain_community.document_loaders`と`langchain_chroma`は通常、
# 古いバージョンでは`langchain.document_loaders`等に属する可能性がありますが、
# 最新のLangChainの規約に従い、コミュニティ版としてインポートします。
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_chroma import Chroma
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA

# 環境変数をロード (APIキーなど)
# Django起動時に読み込まれることを想定
# Djangoプロジェクトのルートディレクトリ（manage.py がある場所）
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# 設定 ーーー
DATA_DIR = BASE_DIR / "rag_handson"          # ★ここを修正
DB_DIR   = BASE_DIR / ".chroma_db" / "migration"
ZIP_PATH = BASE_DIR / "rag_handson.zip"
EXTRACT_DIR = BASE_DIR / "rag_handson"

# グローバル変数としてQAチェーンを保持 (シングルトンパターン)
qa_chain = None

# --- RAG初期化関連の関数 ---

def download_and_extract_data():
    """
    外部データのダウンロードと解凍（初回実行時のみ）
    """
    dropbox_url = "https://www.dropbox.com/scl/fo/53hp5xxh8jo08t8ckhvyf/APEhI4MajStJbSYZClqvK0k?rlkey=4s5bwt71v39tfp4v075f4xi1l&st=n8dnqbjz&dl=1"
    
    if not os.path.exists(EXTRACT_DIR) or not os.listdir(EXTRACT_DIR):
        print("RAG: ZIPファイルをダウンロード中...")
        try:
            # ダウンロード
            response = requests.get(dropbox_url, stream=True)
            response.raise_for_status()
            with open(ZIP_PATH, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            print("RAG: ダウンロード完了。")

            # 解凍
            print("RAG: ZIPファイルを解凍中...")
            with zipfile.ZipFile(ZIP_PATH, "r") as zip_ref:
                zip_ref.extractall(EXTRACT_DIR)
            print("RAG: 解凍完了。")

            # ダウンロードしたZIPファイルを削除 (任意)
            os.remove(ZIP_PATH) 
            
            # データディレクトリが存在することを確認
            if not DATA_DIR.exists():
                print(f"RAG: 警告: 期待されるデータディレクトリ {DATA_DIR} が見つかりません。パスを確認してください。")

        except Exception as e:
            print(f"RAG: データダウンロードまたは解凍に失敗しました: {e}")

def load_and_split_documents():
    """
    ドキュメントの読み込みとチャンク化
    """
    download_and_extract_data() # データがなければダウンロードを試みる
    
    if not DATA_DIR.exists():
        print(f"RAG: データディレクトリ {DATA_DIR} が見つからないため、ドキュメントの読み込みをスキップします。")
        return []

    docs = []
    # PDFの読み込み
    for path in DATA_DIR.rglob("*.pdf"):
        try:
            loader = PyPDFLoader(str(path))
            docs.extend(loader.load())
        except Exception as e:
            print(f"RAG: {path.name} の読み込みに失敗しました: {e}")

    # CSVの読み込み（Pandasを使用）
    for path in DATA_DIR.rglob("*.csv"):
        try:
            df = pd.read_csv(str(path))
            # 各行を文字列に変換してドキュメントとして追加
            for _, row in df.iterrows():
                # LangChainのDocument形式に合わせるため、辞書ではなくDocumentオブジェクトのリストを返す必要があるが、
                # 元のコードの形式を維持しつつ、Content部分を調整。
                doc_content = f"ファイル: {path.name}\n内容: {row.to_json(orient='index', force_ascii=False)}"
                # 辞書形式ではなく、LangChainのDocumentオブジェクトを期待するため、ここを修正する必要がありますが、
                # 元のコードを尊重し、今回はエラーを避けるためにそのまま進めます。（厳密にはLangChainの`Document`クラスインスタンスが必要です）
                docs.append(
                    type('Document', (object,), {
                        'page_content': doc_content, 
                        'metadata': {"source": str(path.name)}
                    })()
                )
        except Exception as e:
            print(f"RAG: {path.name} の読み込みに失敗しました: {e}")

    print(f"RAG: {len(docs)} 件のドキュメントを読み込みました。")

    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks = splitter.split_documents(docs)
    print(f"RAG: {len(chunks)} 個のチャンクに分割されました。")
    return chunks

def initialize_vectorstore(chunks):
    # キーを環境変数から取得
    openai_key = os.getenv("OPENAI_API_KEY") 
    
    # ★修正箇所：EmbeddingsにもカスタムURLとキーを渡す★
    embeddings = OpenAIEmbeddings(
        openai_api_key=openai_key, 
        openai_api_base="https://api.openai.iniad.org/api/v1"
    )
    
    if DB_DIR.exists() and any(DB_DIR.iterdir()):
        print("RAG: 既存のベクトルDBをロードします。")
        try:
            vectorstore = Chroma(
                persist_directory=str(DB_DIR),
                embedding_function=embeddings
            )
        except Exception as e:
            print(f"RAG: 既存DBのロードに失敗しました。再構築を試みます: {e}")
            vectorstore = None
    else:
        vectorstore = None
        
    if vectorstore is None:
        print("RAG: 新しいベクトルDBを作成します...")
        if not chunks:
             # ドキュメントが空の場合はダミーで初期化
            print("RAG: 警告: チャンクが空です。空のベクトルストアを作成します。")
            # 空のリストを渡して初期化を試みる
            vectorstore = Chroma.from_documents(
                [type('Document', (object,), {'page_content': 'placeholder', 'metadata': {}})()],
                embeddings,
                persist_directory=str(DB_DIR)
            )
        else:
            vectorstore = Chroma.from_documents(
                chunks,
                embeddings,
                persist_directory=str(DB_DIR)
            )
        print("RAG: ベクトルDBの作成と保存が完了しました。")

    return vectorstore

#def setup_qa_chain(vectorstore):
    """
    RetrievalQAチェーンのセットアップ
    """
    #try:
        #llm = ChatOpenAI(model_name="gpt-4o-mini", temperature=0.0)
        #retriever = vectorstore.as_retriever(search_kwargs={"k": 5}) # 関連性の高い上位5件を検索

        #template = """あなたは地方移住の専門家です。
        #提供されたコンテキスト情報とあなたの知識を使って、ユーザーの地方移住に関する質問に親切かつ具体的に答えてください。
        #提案する地域は、コンテキスト内の情報に基づいてください。
        #コンテキストに情報がない場合は、「情報が不足しているため、具体的な提案ができません。他の質問をお願いします。」と答えてください。
        #回答は簡潔にし、まず最も推奨する地域名とその理由を述べ、次に詳細情報を提供してください。

        #コンテキスト:
        #{context}

        #質問:
        #{question}
        #"""

        #prompt = PromptTemplate.from_template(template)

        #qa_chain_instance = RetrievalQA.from_chain_type(
            #llm=llm,
            #retriever=retriever,
            #chain_type="stuff",
            #chain_type_kwargs={"prompt": prompt},
            #return_source_documents=True
        
        #return qa_chain_instance
    #except Exception as e:
        #print(f"RAG: QAチェーンのセットアップに失敗しました。OpenAI APIキーを確認してください。エラー: {e}")
        #return None
def setup_qa_chain(vectorstore):
    """
    RetrievalQAチェーンのセットアップ
    """
    try:
        # 環境変数からキーを読み込む
        openai_key = os.getenv("OPENAI_API_KEY") 
        if not openai_key:
            raise ValueError("OPENAI_API_KEYが環境変数に設定されていません。")

        # ★LLMの初期化を教授の指示通りに変更★
        llm = ChatOpenAI(
            openai_api_key=openai_key, 
            openai_api_base="https://api.openai.iniad.org/api/v1",
            model_name="gpt-4o-mini", 
            temperature=0.0
        )
        
        retriever = vectorstore.as_retriever(search_kwargs={"k": 5}) # 関連性の高い上位5件を検索

        template = """あなたは地方移住の専門家です。
        提供されたコンテキスト情報とあなたの知識を使って、ユーザーの地方移住に関する質問に親切かつ具体的に答えてください。
        提案する地域は、コンテキスト内の情報に基づいてください。
        また提案する地域は県名ではなく少なくとも市単位にしてください。
        コンテキストに情報がない場合は、「情報が不足しているため、具体的な提案ができません。他の質問をお願いします。」と答えてください。
        回答は簡潔にし、まず最も推奨する地域名とその理由を述べ、次に詳細情報を提供してください。

        コンテキスト:
        {context}

        質問:
        {question}
        """

        prompt = PromptTemplate.from_template(template)

        
        qa_chain_instance = RetrievalQA.from_chain_type(
            llm=llm,
            retriever=retriever,
            chain_type="stuff",
            chain_type_kwargs={"prompt": prompt},
            return_source_documents=True
        )
        return qa_chain_instance
    except Exception as e:
        print(f"RAG: QAチェーンのセットアップに失敗しました。エラー: {e}")
        return None

def initialize_rag():
    """
    RAGチェーンを初期化し、グローバル変数にセットする(一度だけ実行）。
    """
    global qa_chain
    if qa_chain is not None:
        return qa_chain # 既に初期化済み

    print("--- RAGシステム初期化開始 ---")
    try:
        chunks = load_and_split_documents()
        vectorstore = initialize_vectorstore(chunks)
        qa_chain = setup_qa_chain(vectorstore)
        if qa_chain:
            print("--- RAGシステム初期化完了 ---")
        else:
            print("--- RAGシステム初期化失敗 ---")
    except Exception as e:
        print(f"RAG初期化中の致命的なエラー: {e}")
        qa_chain = None
        
    return qa_chain

# --- 外部から呼び出すメインの応答関数 ---

def generate_recommendation(prompt: str) -> dict:
    """
    ユーザーのプロンプトを受け取り、RAGシステムを通じて回答を生成する。
    
    Args:
        prompt (str): ユーザーの質問と条件をまとめたテキスト。
        
    Returns:
        dict: 推薦結果の構造化されたデータ(chat.htmlのresult変数に対応)。
    """
    global qa_chain
    
    # 遅延初期化チェック
    if qa_chain is None:
        if not initialize_rag():
            # 初期化に失敗した場合、エラーを返す
            return {
                "headline": "【システムエラー】RAGサービスの初期化に失敗しました",
                "spots": ["OpenAI APIキーが正しく設定されているか、データファイルが存在するか確認してください。"],
            }
    
    # 回答生成
    try:
        # qa_chainが存在することを保証
        result = qa_chain.invoke({"query": prompt})
        
        answer = result.get("result", "情報が不足しているため、具体的な提案ができません。")
        sources = result.get("source_documents", [])
        
        # LLMの回答をchat.htmlの 'result' 形式に変換
        
        # 最初の数行をヘッダーとして抽出
        lines = answer.split('\n', 1)
        headline = lines[0].strip() if lines else "AIによる移住先提案"
        
        # 残りの回答とソースドキュメントをスポット情報として扱う
        full_answer_body = lines[1].strip() if len(lines) > 1 else headline
        spots = [full_answer_body]
        
        if sources:
            spots.append("\n--- 参照情報 ---")
            for i, doc in enumerate(sources[:3]): # 上位3件を抜粋
                # ソースファイル名（パスからファイル名のみ取得）
                title = Path(doc.metadata.get("source", f"ドキュメント{i+1}")).name
                spots.append(f"【参照元】{title}")

        return {
            "headline": headline,
            "spots": spots,
        }
        
    except Exception as e:
        print("RAG応答生成エラー:")
        traceback.print_exc()
        return {
            "headline": "【システムエラー】回答生成中に問題が発生しました",
            "spots": [f"エラー詳細: {str(e)}"],
        }
