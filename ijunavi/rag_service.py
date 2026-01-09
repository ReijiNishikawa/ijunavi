import os
import json
import hashlib
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
import traceback
import threading

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
load_dotenv('.env')

# === 設定 ===
DATA_DIR = BASE_DIR / "ijunavi" / "data" / "rag_handson" / "data"
DB_DIR   = BASE_DIR / ".chroma_db" / "migration"

# 使うCSVを固定（ホワイトリスト）
ALLOWED_CSV = {"2024人口.csv", "2024医療.csv", "2024居住.csv", "2024教育.csv", "tenpo2511.csv"}

# CSV更新検知用（DB内に保存）
FINGERPRINT_PATH = DB_DIR / "_fingerprint.json"

# グローバル変数としてQAチェーンを保持
qa_chain = None

RAG_STATUS = {
    "state": "idle",      # idle / building / ready / error
    "total": 0,
    "current": 0,
    "percent": 0,
    "message": "",
    "error": ""
}
RAG_LOCK = threading.Lock()

def get_rag_status():
    with RAG_LOCK:
        return dict(RAG_STATUS)

def _set_status(**kwargs):
    with RAG_LOCK:
        RAG_STATUS.update(kwargs)

def csv_df_to_grouped_docs(df: pd.DataFrame, source_name: str, group_rows: int = 800) -> list[Document]:
    docs = []
    total = len(df)
    for start in range(0, total, group_rows):
        end = min(start + group_rows, total)
        part = df.iloc[start:end]
        text = part.to_json(orient="records", force_ascii=False)
        docs.append(
            Document(
                page_content=f"ファイル: {source_name}\n行: {start+1}-{end}\n内容: {text}",
                metadata={"source": source_name, "row_from": start + 1, "row_to": end},
            )
        )
    return docs

def compute_data_fingerprint() -> dict:
    items = []
    for p in DATA_DIR.rglob("*.csv"):
        if p.name not in ALLOWED_CSV:
            continue
        stat = p.stat()
        items.append({
            "name": p.name,
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
        })
    items.sort(key=lambda x: x["name"])
    payload = {"files": items}
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    payload["hash"] = hashlib.sha256(raw).hexdigest()
    return payload

def load_saved_fingerprint() -> dict | None:
    try:
        if FINGERPRINT_PATH.exists():
            return json.loads(FINGERPRINT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None

def save_fingerprint(fp: dict) -> None:
    os.makedirs(DB_DIR, exist_ok=True)
    FINGERPRINT_PATH.write_text(json.dumps(fp, ensure_ascii=False, indent=2), encoding="utf-8")

def _read_csv_safely(path: Path, **kwargs) -> pd.DataFrame:
    try:
        return pd.read_csv(str(path), low_memory=False, **kwargs)
    except UnicodeDecodeError:
        return pd.read_csv(str(path), low_memory=False, encoding="cp932", **kwargs)

def load_tenpo2511_as_long_df(path: Path) -> pd.DataFrame:
    df = _read_csv_safely(path, header=2)

    if len(df.columns) >= 2:
        df = df.rename(columns={df.columns[0]: "year", df.columns[1]: "timing"})

    for col in ["合計", "集計日", "year", "timing"]:
        if col not in df.columns:
            pass

    id_cols = [c for c in ["year", "timing", "集計日"] if c in df.columns]
    if not id_cols:
        raise ValueError("tenpo2511.csv のヘッダー解析に失敗しました（year/timing/集計日が見つかりません）")

    exclude = set(id_cols) | {"合計"}
    pref_cols = [c for c in df.columns if c not in exclude]

    long_df = df.melt(
        id_vars=id_cols,
        value_vars=pref_cols,
        var_name="prefecture",
        value_name="store_count",
    )

    long_df["store_count"] = pd.to_numeric(long_df["store_count"], errors="coerce")
    long_df = long_df.dropna(subset=["store_count"]).reset_index(drop=True)

    if "集計日" in long_df.columns:
        long_df["date"] = long_df["集計日"].astype(str)
    else:
        long_df["date"] = ""

    if "year" not in long_df.columns:
        long_df["year"] = ""
    if "timing" not in long_df.columns:
        long_df["timing"] = ""

    return long_df[["year", "timing", "date", "prefecture", "store_count"]]

def tenpo_long_df_to_docs(long_df: pd.DataFrame, source_name: str, group_rows: int = 1200) -> list[Document]:
    docs = []
    total = len(long_df)
    for start in range(0, total, group_rows):
        end = min(start + group_rows, total)
        part = long_df.iloc[start:end]

        lines = []
        for _, r in part.iterrows():
            sc = int(r["store_count"]) if pd.notna(r["store_count"]) else r["store_count"]
            lines.append(
                f"スーパー店舗数。{r['year']} {r['timing']}（集計日 {r['date']}）"
                f"{r['prefecture']}の店舗数は{sc}。"
            )

        docs.append(
            Document(
                page_content="\n".join(lines),
                metadata={"source": source_name, "row_from": start + 1, "row_to": end},
            )
        )
    return docs

# --- RAG初期化関連の関数 ---
def load_and_split_documents():
    if not DATA_DIR.exists():
        print(f"RAGエラー: データディレクトリ '{DATA_DIR.resolve()}' が見つかりません。")
        return []

    docs = []
    print(f"RAG: '{DATA_DIR}' 内のCSVファイルをスキャン中...（CSVのみ使用）")

    csv_files = [p for p in DATA_DIR.rglob("*.csv") if p.name in ALLOWED_CSV]
    for path in csv_files:
        try:
            if path.name == "tenpo2511.csv":
                long_df = load_tenpo2511_as_long_df(path)
                grouped_docs = tenpo_long_df_to_docs(long_df, source_name=path.name, group_rows=1200)
                docs.extend(grouped_docs)
                print(f"  - 読込成功: {path.name}（{len(long_df)}行(整形後) → {len(grouped_docs)}docs）")
            else:
                df = _read_csv_safely(path)
                grouped_docs = csv_df_to_grouped_docs(df, source_name=path.name, group_rows=800)
                docs.extend(grouped_docs)
                print(f"  - 読込成功: {path.name}（{len(df)}行 → {len(grouped_docs)}docs）")

        except Exception as e:
            print(f"  - 読込失敗: {path.name} ({e})")

    skipped = [p.name for p in DATA_DIR.rglob("*.csv") if p.name not in ALLOWED_CSV]
    if skipped:
        print(f"RAG: 対象外CSVは読み込みません: {', '.join(skipped)}")

    print(f"RAG: 合計 {len(docs)} 件のドキュメントを読み込みました。")

    splitter = RecursiveCharacterTextSplitter(chunk_size=15000, chunk_overlap=0)
    chunks = splitter.split_documents(docs)
    print(f"RAG: {len(chunks)} 個のチャンクに分割されました。")
    return chunks

def initialize_vectorstore(chunks):
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        raise ValueError("OPENAI_API_KEYが環境変数に設定されていません。")

    os.environ["OPENAI_API_KEY"] = openai_key
    os.environ["OPENAI_BASE_URL"] = "https://api.openai.iniad.org/api/v1"

    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small",
        openai_api_key=openai_key,
        openai_api_base="https://api.openai.iniad.org/api/v1",
        chunk_size=25
    )

    current_fp = compute_data_fingerprint()
    saved_fp = load_saved_fingerprint()
    db_exists = DB_DIR.exists() and any(DB_DIR.iterdir())

    if db_exists and saved_fp and saved_fp.get("hash") == current_fp.get("hash"):
        print("RAG: 既存のベクトルDBをロードします。（CSV変更なし）")
        _set_status(
            state="ready",
            total=0,
            current=0,
            percent=100,
            message="ベクトルDBは既に作成済みです。",
            error=""
        )
        vectorstore = Chroma(
            persist_directory=str(DB_DIR),
            embedding_function=embeddings
        )
        return vectorstore

    if db_exists:
        print("RAG: CSVが更新されたため、既存DBを削除して再作成します。")
        import shutil
        shutil.rmtree(DB_DIR, ignore_errors=True)

    print("RAG: 新しいベクトルDBを作成します...")
    os.makedirs(DB_DIR, exist_ok=True)

    vectorstore = Chroma(
        embedding_function=embeddings,
        persist_directory=str(DB_DIR),
    )

    total = len(chunks)
    _set_status(
        state="building",
        total=total,
        current=0,
        percent=0,
        message=f"ベクトルDB作成中... 0/{total}",
        error=""
    )

    batch_size = 200
    for i in range(0, total, batch_size):
        batch = chunks[i:i + batch_size]
        vectorstore.add_documents(batch)

        done = i + len(batch)
        percent = int(done * 100 / total) if total else 100
        _set_status(
            state="building",
            total=total,
            current=done,
            percent=percent,
            message=f"ベクトルDB作成中... {done}/{total}",
            error=""
        )

    save_fingerprint(current_fp)

    _set_status(
        state="ready",
        total=total,
        current=total,
        percent=100,
        message="ベクトルDB作成が完了しました。",
        error=""
    )

    print("RAG: ベクトルDBの作成と保存が完了しました。")
    return vectorstore

def setup_qa_chain(vectorstore):
    try:
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            raise ValueError("OPENAI_API_KEYが環境変数に設定されていません。")

        os.environ["OPENAI_API_KEY"] = openai_key
        os.environ["OPENAI_BASE_URL"] = "https://api.openai.iniad.org/api/v1"

        llm = ChatOpenAI(
            model_name="gpt-4o-mini",
            openai_api_key=openai_key,
            openai_api_base="https://api.openai.iniad.org/api/v1",
            temperature=0.0,
        )

        retriever = vectorstore.as_retriever(
            search_type="mmr",
            search_kwargs={
                "k": 4,
                "fetch_k": 10,
                "lambda_mult": 0.5
            },
        )

        template = """あなたは地方移住の専門家です。
        提供されたコンテキスト情報のみを使用して、ユーザーの質問に回答してください。
        回答は必ず以下の【出力形式】に従って作成してください。
        各理由は、必ずコンテキスト内のどのデータ（ファイル名）を参照したかを明記してください。
        【出力形式】
        ■結論：(最も推奨する地域名とその一言要約)
        ■理由1（参照：[ファイル名]）
        (その地域を推奨する具体的な理由や特徴)
        \n
        ■理由2（参照：[ファイル名]）
        (別の観点からの理由や特徴)
        (必要に応じて理由を追加...)
        \n
        ■補足・アドバイス
        (移住にあたっての注意点など)
        \n
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
    global qa_chain
    if qa_chain is not None:
        return qa_chain

    print("--- RAGシステム初期化開始 ---")
    try:
        current_fp = compute_data_fingerprint()
        saved_fp = load_saved_fingerprint()
        db_exists = DB_DIR.exists() and any(DB_DIR.iterdir())

        if db_exists and saved_fp and saved_fp.get("hash") == current_fp.get("hash"):
            print("RAG: CSV変更なしのため、チャンク作成をスキップします。")
            chunks = []
        else:
            chunks = load_and_split_documents()

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

def generate_recommendation(prompt: str) -> dict:
    global qa_chain

    if qa_chain is None:
        if not initialize_rag():
            return {
                "headline": "【システムエラー】RAGサービスの初期化に失敗しました",
                "spots": ["データフォルダ(data)にファイルがあるか、APIキーが正しいか確認してください。"],
            }

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
            seen_sources = set()
            count = 0
            for doc in sources:
                src = Path(doc.metadata.get("source", "不明")).name
                if src not in seen_sources:
                    spots.append(f"【参照元】{src}")
                    seen_sources.add(src)
                    count += 1
                    if count >= 3:
                        break

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
