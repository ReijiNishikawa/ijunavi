import os
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
import traceback
# LangChain/LLM 関連のインポート
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_chroma import Chroma
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from django.conf import settings
from langchain.schema import Document

# プロジェクトルート（manage.py がある場所）
BASE_DIR = settings.BASE_DIR
# 環境変数をロード
load_dotenv(BASE_DIR / ".env")
# === 設定 ===
# ★重要★: ここで指定したフォルダの中に、手動でPDFやCSVを入れてください
DATA_DIR = BASE_DIR / "ijunavi" / "data" / "rag_handson" / "data"
# ChromaDBの保存先
DB_DIR   = BASE_DIR / ".chroma_db" / "migration"
# グローバル変数としてQAチェーンを保持
qa_chain = None
# --- RAG初期化関連の関数 ---
def load_and_split_documents():
    """
    ドキュメントの読み込みとチャンク化
    (ダウンロード機能は削除済み。DATA_DIRにあるファイルを読み込みます)
    """
    # ディレクトリの存在確認
    if not DATA_DIR.exists():
        print(f"RAGエラー: データディレクトリ '{DATA_DIR.resolve()}' が見つかりません。")
        print("フォルダを作成し、PDFやCSVファイルを手動で配置してください。")
        return []
    docs = []
    print(f"RAG: '{DATA_DIR}' 内のファイルをスキャン中...")
    # PDFの読み込み
    pdf_files = list(DATA_DIR.rglob("*.pdf"))
    for path in pdf_files:
        try:
            loader = PyPDFLoader(str(path))
            docs.extend(loader.load())
            print(f"  - 読込成功: {path.name}")
        except Exception as e:
            print(f"  - 読込失敗: {path.name} ({e})")
    # CSVの読み込み
    csv_files = list(DATA_DIR.rglob("*.csv"))
    for path in csv_files:
        try:
            df = pd.read_csv(str(path), low_memory=False)
            for _, row in df.iterrows():
                doc_content = f"ファイル: {path.name}\n内容: {row.to_json(orient='index', force_ascii=False)}"
                # 簡易的なDocumentオブジェクトの作成
                docs.append(
                    Document(
                        page_content=doc_content,
                        metadata={"source": str(path.name)}
                    )
                )
            print(f"  - 読込成功: {path.name}")
        except Exception as e:
            print(f"  - 読込失敗: {path.name} ({e})")
    if not docs:
        print("RAG警告: 読み込めるドキュメントが0件でした。")
        return []
    print(f"RAG: 合計 {len(docs)} 件のドキュメント（行/ページ）を読み込みました。")
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks = splitter.split_documents(docs)
    print(f"RAG: {len(chunks)} 個のチャンクに分割されました。")
    return chunks
def initialize_vectorstore(chunks):
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        raise ValueError("OPENAI_API_KEYが環境変数に設定されていません。")

    # 念のため openai ライブラリ用にも環境変数をセット
    os.environ["OPENAI_API_KEY"] = openai_key
    os.environ["OPENAI_BASE_URL"] = "https://api.openai.iniad.org/api/v1"

    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small",
        openai_api_key=openai_key,
        openai_api_base="https://api.openai.iniad.org/api/v1",
    )

    # 既存DBの確認とロード
    if DB_DIR.exists() and any(DB_DIR.iterdir()):
        print("RAG: 既存のベクトルDBをロードします。")
        try:
            vectorstore = Chroma(
                persist_directory=str(DB_DIR),
                embedding_function=embeddings
            )
            return vectorstore
        except Exception as e:
            print(f"RAG: 既存DBのロードに失敗しました: {e}")
            # 失敗したら再作成へ進む

    # 新規作成
    print("RAG: 新しいベクトルDBを作成します...")
    if not chunks:
        print("RAG警告: チャンクが空です。空のベクトルストアを作成します（検索機能は動作しません）。")
        # 空コレクションだけ作成
        vectorstore = Chroma(
            embedding_function=embeddings,
            persist_directory=str(DB_DIR),
        )
    else:
        # 空の Chroma コレクションを作ってから、バッチで追加
        os.makedirs(DB_DIR, exist_ok=True)
        vectorstore = Chroma(
            embedding_function=embeddings,
            persist_directory=str(DB_DIR),
        )

        batch_size = 1000  # ← 上限5461よりだいぶ小さくして安全側に
        total = len(chunks)
        for i in range(0, total, batch_size):
            batch = chunks[i:i + batch_size]
            print(f"RAG: ベクトルDBに追加中... {i} 〜 {i + len(batch) - 1} / {total}")
            vectorstore.add_documents(batch)

    print("RAG: ベクトルDBの作成と保存が完了しました。")
    return vectorstore
def setup_qa_chain(vectorstore):
    try:
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            raise ValueError("OPENAI_API_KEYが環境変数に設定されていません。")

        os.environ["OPENAI_API_KEY"] = openai_key
        os.environ["OPENAI_BASE_URL"] = "https://api.openai.iniad.org/api/v1"

        # ここを追加：embeddings を setup_qa_chain 内で定義
        embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small",
            openai_api_key=openai_key,
            openai_api_base="https://api.openai.iniad.org/api/v1",
        )

        llm = ChatOpenAI(
            model_name="gpt-4o-mini",
            openai_api_key=openai_key,
            openai_api_base="https://api.openai.iniad.org/api/v1",
            temperature=0.0,
        )

        # 多様性サンプリング retriever の構築
                # Chroma の MMR 検索で多様性を確保する retriever
        retriever = vectorstore.as_retriever(
            search_type="mmr",
            search_kwargs={
                "k": 4,
                "fetch_k": 10,
                "lambda_mult": 0.5
            },
        )

        # RetrievalQA（retriever モード）
        template = """あなたは地方移住の専門家です。
        提供されたコンテキスト情報とあなたの知識を使って、ユーザーの地方移住に関する質問に親切かつ具体的に答えてください。
        提案する地域は、コンテキスト内の情報に基づいてください。
        また提案する地域は県名ではなく少なくとも市単位にしてください。
        出力する際には参考にしたdataのファイル名を記載してください
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
    RAGチェーンを初期化し、グローバル変数にセットする
    """
    global qa_chain
    if qa_chain is not None:
        return qa_chain
    print("--- RAGシステム初期化開始 ---")
    try:
        chunks = load_and_split_documents()
        # チャンクがなくても（ファイルがなくても）とりあえずDB初期化へ進む（エラーで落ちないように）
        vectorstore = initialize_vectorstore(chunks)
        qa_chain = setup_qa_chain(vectorstore)
        if qa_chain:
            print("--- RAGシステム初期化完了 ---")
        else:
            print("--- RAGシステム初期化失敗 ---")
    except Exception as e:
        print(f"RAG初期化中の致命的なエラー: {e}")
        traceback.print_exc()
        qa_chain = None
    return qa_chain
# --- 外部から呼び出すメインの応答関数 ---
def generate_recommendation(prompt: str) -> dict:
    global qa_chain
    # 遅延初期化チェック
    if qa_chain is None:
        if not initialize_rag():
            return {
                "headline": "【システムエラー】RAGサービスの初期化に失敗しました",
                "spots": ["データフォルダ(data)にファイルがあるか、APIキーが正しいか確認してください。"],
            }
    # 回答生成
    try:
        result = qa_chain.invoke({"query": prompt})
        answer = result.get("result", "情報が不足しているため、具体的な提案ができません。")
        sources = result.get("source_documents", [])
        lines = answer.split('\n', 1)
        headline = lines[0].strip() if lines else "AIによる移住先提案"
        full_answer_body = lines[1].strip() if len(lines) > 1 else headline
        spots = [full_answer_body]
        if sources:
            spots.append("\n--- 参照情報 ---")
            # 重複を除去しつつ上位を表示
            seen_sources = set()
            count = 0
            for doc in sources:
                src = Path(doc.metadata.get("source", "不明")).name
                if src not in seen_sources:
                    spots.append(f"【参照元】{src}")
                    seen_sources.add(src)
                    count += 1
                    if count >= 3: break
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