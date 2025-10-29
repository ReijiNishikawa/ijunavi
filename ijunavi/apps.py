from django.apps import AppConfig
import os
import pandas as pd
import zipfile
import requests
from pathlib import Path

import gradio as gr
from dotenv import load_dotenv

from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_chroma import Chroma
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA

class IjunaviConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ijunavi'


# 環境変数をロード
load_dotenv()

# === 設定 ===
DATA_DIR = "./data"
DB_DIR = "./chroma_db/migration"

# 外部データのダウンロードと解凍（任意）
def download_and_extract_data():
    dropbox_url = "https://www.dropbox.com/scl/fo/53hp5xxh8jo08t8ckhvyf/APEhI4MajStJbSYZClqvK0k?rlkey=4s5bwt71v39tfp4v075f4xi1l&st=n8dnqbjz&dl=1"
    zip_path = "rag_handson.zip"
    extract_dir = "rag_handson"

    if not os.path.exists(extract_dir):
        print("Downloading ZIP from Dropbox...")
        try:
            with requests.get(dropbox_url, stream=True) as r:
                r.raise_for_status()
                with open(zip_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            print("Download complete.")

            print("Extracting ZIP...")
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(extract_dir)
            print("Extraction complete.")
        except Exception as e:
            print(f"データダウンロードまたは解凍に失敗しました: {e}")

# ドキュメントの読み込みとチャンク化
def load_and_split_documents():
    docs = []
    # PDFの読み込み
    for path in Path(DATA_DIR).rglob("*.pdf"):
        try:
            loader = PyPDFLoader(str(path))
            docs.extend(loader.load())
        except Exception as e:
            print(f"{path.name} の読み込みに失敗しました: {e}")

    # CSVの読み込み（Pandasを使用）
    for path in Path(DATA_DIR).rglob("*.csv"):
        try:
            df = pd.read_csv(str(path))
            # 各行を文字列に変換してドキュメントとして追加
            for _, row in df.iterrows():
                doc_content = f"ファイル: {path.name}\n内容: {row.to_json(orient='index', force_ascii=False)}"
                docs.append({"page_content": doc_content, "metadata": {"source": str(path.name)}})
        except Exception as e:
            print(f" {path.name} の読み込みに失敗しました: {e}")

    print(f" {len(docs)} 件のドキュメントを読み込みました。")

    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks = splitter.split_documents(docs)
    print(f" {len(chunks)} 個のチャンクに分割されました。")
    return chunks

# ベクトルストアの初期化
def initialize_vectorstore(chunks):
    if os.path.exists(DB_DIR) and os.path.isdir(DB_DIR):
        print(" 既存のベクトルDBをロードします。")
        vectorstore = Chroma(
            persist_directory=DB_DIR,
            embedding_function=OpenAIEmbeddings()
        )
    else:
        print(" 新しいベクトルDBを作成します...")
        embeddings = OpenAIEmbeddings()
        vectorstore = Chroma.from_documents(
            chunks,
            embeddings,
            persist_directory=DB_DIR
        )
        print(" ベクトルDBの作成と保存が完了しました。")

    return vectorstore

# QAチェーンのセットアップ
def setup_qa_chain(vectorstore):
    llm = ChatOpenAI(model_name="gpt-4o-mini", temperature=0.0)
    retriever = vectorstore.as_retriever(search_kwargs={"k": 5}) # 関連性の高い上位5件を検索

    template = """あなたは地方移住の専門家です。
    提供されたコンテキスト情報とあなたの知識を使って、ユーザーの地方移住に関する質問に親切かつ具体的に答えてください。
    提案する地域は、コンテキスト内の情報に基づいてください。
    コンテキストに情報がない場合は、「情報が不足しているため、具体的な提案ができません」と答えてください。

    コンテキスト:
    {context}

    質問:
    {question}
    """

    prompt = PromptTemplate.from_template(template)

    qa_chain = RetrievalQA.from_chain_type(
        llm=llm,
        retriever=retriever,
        chain_type="stuff",
        chain_type_kwargs={"prompt": prompt},
        return_source_documents=True
    )
    return qa_chain

# 回答関数
def chat_response(message, history):
    try:
        result = qa_chain.invoke({"query": message})
        answer = result.get("result", "情報が不足しているため、具体的な提案ができません。")
        sources = result.get("source_documents", [])

        formatted_sources = []
        if sources:
            for i, doc in enumerate(sources):
                title = doc.metadata.get("source", f"ドキュメント{i+1}")
                snippet = doc.page_content.strip().replace("\n", " ").replace("　", " ")
                snippet = snippet[:300] + ("…" if len(snippet) > 300 else "")
                formatted_sources.append(f"""【{i+1}. {title}】\n{snippet}""")

            sources_text = "\n---\n".join(formatted_sources)
            full_response = f"{answer}\n\n📄 **参照データ**\n{sources_text}"
        else:
            full_response = answer

        return full_response
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"エラーが発生しました: {str(e)}"

# メイン処理
if __name__ == "__main__":
    # データのダウンロード（初回実行時のみ）
    download_and_extract_data()

    # ドキュメントの読み込みとベクトルDBの構築
    chunks = load_and_split_documents()
    vectorstore = initialize_vectorstore(chunks)

    # QAチェーンのセットアップ
    qa_chain = setup_qa_chain(vectorstore)

    # Gradio UIの起動
    ui = gr.ChatInterface(
        fn=chat_response,
        title="地方移住コンシェルジュ（RAG）",
        description="あなたの希望条件に合った地方移住先を提案します。データはe-Stat、不動産、交通情報に基づいています。",
        examples=["子育てがしやすい地域を教えてください", "静かで自然豊かな地域で、家賃が安いところはありますか？"],
        submit_btn="送信",
        stop_btn="停止"
    )
    ui.launch()