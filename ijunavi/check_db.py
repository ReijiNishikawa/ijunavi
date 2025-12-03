import os
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from dotenv import load_dotenv

# 1. 環境設定の読み込み
load_dotenv("templates/.env")

# 2. データベースの場所を指定（設定と合わせる）
DB_DIR = "./chroma_db/migration"

def check_chroma_content():
    print(f"--- {DB_DIR} の中身を確認します ---")
    
    # APIキーの準備（DBを開くために必要）
    openai_key = os.getenv("OPENAI_API_KEY")
    embeddings = OpenAIEmbeddings(
        openai_api_key=openai_key, 
        openai_api_base="https://api.openai.iniad.org/api/v1"
    )

    # 3. データベースに接続
    try:
        vectorstore = Chroma(
            persist_directory=DB_DIR,
            embedding_function=embeddings
        )
        
        # 4. データを取得する（LangChain経由で全件取得はできないため、内部メソッドを使用）
        # limit=5 で「最初の5件だけ」を表示します
        data = vectorstore.get(limit=5)
        
        ids = data['ids']
        documents = data['documents']
        metadatas = data['metadatas']
        
        total_count = len(vectorstore.get()['ids']) # 全件数を取得
        
        print(f"★ 保存されているデータの総数（チャンク数）: {total_count} 件")
        print("-" * 50)

        if total_count == 0:
            print("データが空です。読み込みに失敗している可能性があります。")
            return

        # 中身を少しだけ表示
        for i in range(len(ids)):
            print(f"【データ No.{i+1}】")
            print(f"ID: {ids[i]}")
            print(f"元ファイル: {metadatas[i].get('source', '不明')}")
            # 本文が長いので最初の100文字だけ表示
            content_preview = documents[i][:100].replace('\n', '') 
            print(f"内容（冒頭）: {content_preview}...") 
            print("-" * 50)

    except Exception as e:
        print(f"エラーが発生しました: {e}")
        print("chroma_dbフォルダが存在しないか、パスが間違っている可能性があります。")

if __name__ == "__main__":
    check_chroma_content()