"""Sentiment pipeline for X/Twitter data using cardiffnlp/twitter-xlm-roberta-base-sentiment."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import torch
from scipy.special import softmax
from transformers import AutoConfig, AutoModelForSequenceClassification, AutoTokenizer


MODEL_NAME = "cardiffnlp/twitter-xlm-roberta-base-sentiment"
logger = logging.getLogger("sentiment_pipeline")


def preprocess(text: str) -> str:
    new_text: list[str] = []
    for t in str(text).split(" "):
        if t.startswith("@") and len(t) > 1:
            t = "@user"
        elif t.startswith("http"):
            t = "http"
        new_text.append(t)
    return " ".join(new_text)


def _batch_iter(items: list[str], batch_size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), batch_size):
        yield items[i : i + batch_size]


def _canonical_label(label: str) -> str:
    lower = label.strip().lower()
    if "neg" in lower:
        return "negative"
    if "neu" in lower:
        return "neutral"
    if "pos" in lower:
        return "positive"
    return lower


def _resolve_date_column(df: pd.DataFrame) -> str:
    if "date" in df.columns:
        return "date"
    if "datetime" in df.columns:
        return "datetime"
    raise ValueError("Missing date column. Expected 'date' or 'datetime'.")


def _build_label_maps(config: AutoConfig) -> tuple[list[str], dict[str, int], dict[str, int]]:
    num_labels = int(getattr(config, "num_labels", 3))
    index_to_label = []
    for i in range(num_labels):
        raw_label = config.id2label.get(i, f"LABEL_{i}") if hasattr(config, "id2label") else f"LABEL_{i}"
        index_to_label.append(_canonical_label(raw_label))

    expected = {"negative", "neutral", "positive"}
    if set(index_to_label) != expected:
        index_to_label = ["negative", "neutral", "positive"]

    label_to_index = {label: idx for idx, label in enumerate(index_to_label)}
    label_to_score = {"negative": -1, "neutral": 0, "positive": 1}
    return index_to_label, label_to_index, label_to_score


def infer_sentiment(
    df: pd.DataFrame,
    model: AutoModelForSequenceClassification,
    tokenizer: AutoTokenizer,
    label_to_index: dict[str, int],
    label_to_score: dict[str, int],
    device: torch.device,
    batch_size: int,
    max_length: int,
) -> pd.DataFrame:
    texts = df["content"].fillna("").astype(str).tolist()
    labels: list[str] = []
    scores: list[int | None] = []
    prob_negative: list[float | None] = []
    prob_neutral: list[float | None] = []
    prob_positive: list[float | None] = []

    for batch in _batch_iter(texts, batch_size):
        batch_pre = [preprocess(t) for t in batch]
        inputs = tokenizer(
            batch_pre,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=max_length,
        )
        inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.no_grad():
            outputs = model(**inputs)
        logits = outputs.logits.detach().cpu().numpy()
        probs = softmax(logits, axis=1)

        for row in probs:
            idx = int(np.argmax(row))
            label = _canonical_label(model.config.id2label.get(idx, "negative"))
            labels.append(label)
            scores.append(label_to_score.get(label))

            neg_idx = label_to_index.get("negative")
            neu_idx = label_to_index.get("neutral")
            pos_idx = label_to_index.get("positive")
            prob_negative.append(float(row[neg_idx]) if neg_idx is not None else None)
            prob_neutral.append(float(row[neu_idx]) if neu_idx is not None else None)
            prob_positive.append(float(row[pos_idx]) if pos_idx is not None else None)

    df_out = df.copy()
    df_out["sentiment"] = labels
    df_out["sentiment_score"] = scores
    df_out["prob_negative"] = prob_negative
    df_out["prob_neutral"] = prob_neutral
    df_out["prob_positive"] = prob_positive
    return df_out


def build_time_features(df: pd.DataFrame, date_col: str, freq: str) -> pd.DataFrame:
    df_out = df.copy()
    df_out["date_ts"] = pd.to_datetime(df_out[date_col], errors="coerce", utc=True)
    df_out = df_out[df_out["date_ts"].notna()].copy()
    df_out["period"] = df_out["date_ts"].dt.to_period(freq).dt.to_timestamp()

    likes = pd.to_numeric(df_out.get("likes"), errors="coerce").fillna(0)
    retweets = pd.to_numeric(df_out.get("retweets"), errors="coerce").fillna(0)
    df_out["interactions"] = likes + retweets

    agg = (
        df_out.groupby("period", dropna=True)
        .agg(
            puntuacion_de_sentimiento=("sentiment_score", "mean"),
            tasa_de_interaccion=("interactions", "mean"),
            volumen_de_tuits=("id", "count"),
            indice_de_polarizacion=(
                "sentiment_score",
                lambda s: float(s.std(ddof=0)) if len(s) else 0.0,
            ),
        )
        .reset_index()
    )
    return agg


def prepare_model_features(agg_df: pd.DataFrame) -> pd.DataFrame:
    feature_cols = [
        "puntuacion_de_sentimiento",
        "tasa_de_interaccion",
        "volumen_de_tuits",
        "indice_de_polarizacion",
    ]
    features = agg_df[feature_cols].copy()
    # Future work:
    # - Add demographics and electoral context features.
    # - Add geo aggregation if municipality data is available.
    return features


def main() -> None:
    parser = argparse.ArgumentParser(description="Sentiment pipeline for tweets_colombia.csv")
    parser.add_argument("--input", default="tweets_colombia.csv", help="Input CSV path")
    parser.add_argument("--output", default="tweets_colombia_sentiment.csv", help="Output CSV with sentiment")
    parser.add_argument("--agg-output", default="tweets_colombia_agg.csv", help="Output CSV with time features")
    parser.add_argument("--freq", default="W", help="Aggregation frequency (W or M)")
    parser.add_argument("--batch-size", type=int, default=32, help="Batch size for inference")
    parser.add_argument("--max-length", type=int, default=128, help="Max token length")
    parser.add_argument("--device", default=None, help="Device override (cpu or cuda)")
    parser.add_argument("--log-level", default="INFO", help="Log level")
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level, format="%(asctime)s [%(levelname)s] %(message)s")

    input_path = Path(args.input)
    output_path = Path(args.output)
    agg_output_path = Path(args.agg_output)

    df = pd.read_csv(input_path)
    if "content" not in df.columns:
        raise ValueError("Missing 'content' column in input CSV.")

    date_col = _resolve_date_column(df)

    device = torch.device(args.device) if args.device else torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("Loading model %s on %s", MODEL_NAME, device)

    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    config = AutoConfig.from_pretrained(MODEL_NAME)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
    model.to(device)
    model.eval()

    _, label_to_index, label_to_score = _build_label_maps(config)

    df_sent = infer_sentiment(
        df,
        model,
        tokenizer,
        label_to_index,
        label_to_score,
        device,
        args.batch_size,
        args.max_length,
    )
    df_sent.to_csv(output_path, index=False)
    logger.info("Saved sentiment output to %s", output_path)

    agg_df = build_time_features(df_sent, date_col=date_col, freq=args.freq)
    agg_df.to_csv(agg_output_path, index=False)
    logger.info("Saved aggregated features to %s", agg_output_path)

    _ = prepare_model_features(agg_df)


if __name__ == "__main__":
    main()
