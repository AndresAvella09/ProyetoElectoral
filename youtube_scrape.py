"""
YouTube comment + reply collector for Colombian electoral discourse.

Output schema per row (youtube_data.csv):
    id, parent_id, date, text, username, likes, views, video_id,
    video_title, query, source_type

`parent_id` is empty for top-level comments and contains the parent comment id
for replies, so threads can be reconstructed downstream.
"""

import os
import csv
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

YOUTUBE_QUERIES = [
    "elecciones Colombia 2026",
    "candidatos presidenciales Colombia",
    "debate presidencial Colombia",
]

YOUTUBE_VIDEOS_PER_QUERY = 20
YOUTUBE_COMMENTS_PER_VIDEO = 20
YOUTUBE_REPLIES_PER_COMMENT = 50

# Only search videos published in the last N days (bias toward fresh content
# on daily re-runs). Set to None to disable the filter.
YOUTUBE_PUBLISHED_WITHIN_DAYS = 7

OUTPUT_CSV = os.path.join(os.path.dirname(__file__), "youtube_data.csv")

CSV_FIELDS = [
    "id", "parent_id", "date", "text", "username", "likes",
    "views", "video_id", "video_title", "query", "source_type",
]


def _row(id_, parent_id, date, text, username, likes, views,
         video_id, video_title, query):
    return {
        "id":          str(id_),
        "parent_id":   str(parent_id) if parent_id else "",
        "date":        date,
        "text":        (text or "").strip(),
        "username":    username,
        "likes":       int(likes),
        "views":       int(views),
        "video_id":    video_id,
        "video_title": (video_title or "").strip(),
        "query":       query,
    }


def _youtube_client():
    if not YOUTUBE_API_KEY:
        raise ValueError("YOUTUBE_API_KEY not set in .env")
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


def _load_existing_ids(path: str) -> set[str]:
    """Return the set of comment ids already present in the CSV."""
    if not os.path.exists(path):
        return set()
    ids = set()
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cid = row.get("id")
            if cid:
                ids.add(cid)
    return ids


def _search_videos(yt, query: str) -> list[dict]:
    search_kwargs = dict(
        q=query,
        part="snippet",
        type="video",
        maxResults=YOUTUBE_VIDEOS_PER_QUERY,
        relevanceLanguage="es",
        regionCode="CO",
        order="date" if YOUTUBE_PUBLISHED_WITHIN_DAYS else "relevance",
    )
    if YOUTUBE_PUBLISHED_WITHIN_DAYS:
        cutoff = datetime.now(timezone.utc) - timedelta(days=YOUTUBE_PUBLISHED_WITHIN_DAYS)
        search_kwargs["publishedAfter"] = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    resp = yt.search().list(**search_kwargs).execute()

    video_ids = [item["id"]["videoId"] for item in resp.get("items", [])]
    if not video_ids:
        return []

    stats_resp = yt.videos().list(
        id=",".join(video_ids),
        part="statistics,snippet",
    ).execute()

    videos = []
    for item in stats_resp.get("items", []):
        videos.append({
            "video_id":     item["id"],
            "title":        item["snippet"]["title"],
            "channel":      item["snippet"]["channelTitle"],
            "published_at": item["snippet"]["publishedAt"],
            "view_count":   int(item["statistics"].get("viewCount", 0)),
        })
    return videos


def _fetch_replies(yt, parent_id: str, video: dict, query: str) -> list[dict]:
    """Fetch all replies for a top-level comment, paginating as needed."""
    replies = []
    page_token = None
    fetched = 0

    while fetched < YOUTUBE_REPLIES_PER_COMMENT:
        try:
            resp = yt.comments().list(
                parentId=parent_id,
                part="snippet",
                maxResults=min(100, YOUTUBE_REPLIES_PER_COMMENT - fetched),
                textFormat="plainText",
                pageToken=page_token,
            ).execute()
        except HttpError as e:
            if e.resp.status in (403, 404):
                return replies
            raise

        for item in resp.get("items", []):
            c = item["snippet"]
            replies.append(_row(
                id_         = f"yt_{item['id']}",
                parent_id   = f"yt_{parent_id}",
                date        = c["publishedAt"].replace("T", " ").replace("Z", ""),
                text        = c["textDisplay"],
                username    = c["authorDisplayName"],
                likes       = c.get("likeCount", 0),
                views       = video["view_count"],
                video_id    = video["video_id"],
                video_title = video["title"],
                query       = query,
            ))
            fetched += 1

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return replies


def _get_comments(yt, video: dict, query: str) -> list[dict]:
    """Fetch top-level comments + their replies for one video."""
    try:
        resp = yt.commentThreads().list(
            videoId=video["video_id"],
            part="snippet,replies",
            maxResults=YOUTUBE_COMMENTS_PER_VIDEO,
            textFormat="plainText",
            order="relevance",
        ).execute()
    except HttpError as e:
        if e.resp.status in (403, 404):
            return []
        raise

    rows = []
    for item in resp.get("items", []):
        top = item["snippet"]["topLevelComment"]
        top_id = top["id"]
        c = top["snippet"]
        total_replies = item["snippet"].get("totalReplyCount", 0)

        rows.append(_row(
            id_         = f"yt_{top_id}",
            parent_id   = "",
            date        = c["publishedAt"].replace("T", " ").replace("Z", ""),
            text        = c["textDisplay"],
            username    = c["authorDisplayName"],
            likes       = c.get("likeCount", 0),
            views       = video["view_count"],
            video_id    = video["video_id"],
            video_title = video["title"],
            query       = query,
        ))

        if total_replies == 0:
            continue

        inline = item.get("replies", {}).get("comments", [])
        if inline and total_replies <= len(inline):
            for r in inline:
                rc = r["snippet"]
                rows.append(_row(
                    id_         = f"yt_{r['id']}",
                    parent_id   = f"yt_{top_id}",
                    date        = rc["publishedAt"].replace("T", " ").replace("Z", ""),
                    text        = rc["textDisplay"],
                    username    = rc["authorDisplayName"],
                    likes       = rc.get("likeCount", 0),
                    views       = video["view_count"],
                    video_id    = video["video_id"],
                    video_title = video["title"],
                    query       = query,
                ))
        else:
            rows.extend(_fetch_replies(yt, top_id, video, query))

    return rows


def collect(existing_ids: set[str] | None = None) -> list[dict]:
    if not YOUTUBE_API_KEY:
        print("  [YouTube] Skipped — YOUTUBE_API_KEY not set in .env")
        return []

    if existing_ids is None:
        existing_ids = set()

    yt = _youtube_client()
    results = []
    seen = set(existing_ids)

    for query in YOUTUBE_QUERIES:
        try:
            videos = _search_videos(yt, query)
        except HttpError as e:
            print(f"  [YouTube] Search failed ({query!r}): {e}")
            continue

        total_comments = 0
        total_replies = 0
        for video in videos:
            rows = _get_comments(yt, video, query)
            new_rows = [r for r in rows if r["id"] not in seen]
            seen.update(r["id"] for r in new_rows)
            results.extend(new_rows)
            total_comments += sum(1 for r in new_rows if not r["parent_id"])
            total_replies  += sum(1 for r in new_rows if r["parent_id"])
            time.sleep(0.05)

        print(f"    [YouTube] {query!r}: {len(videos)} videos, "
              f"{total_comments} new comments, {total_replies} new replies")

    return results


def save(posts: list[dict], path: str = OUTPUT_CSV) -> None:
    if not posts:
        print("  No posts to save.")
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    file_exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(posts)
    print(f"  Saved {len(posts)} rows → {path}")


if __name__ == "__main__":
    print(f"[{datetime.now().isoformat(timespec='seconds')}] Collecting from YouTube…")
    existing = _load_existing_ids(OUTPUT_CSV)
    print(f"  {len(existing)} ids already in {os.path.basename(OUTPUT_CSV)} — will be skipped")
    posts = collect(existing_ids=existing)
    print(f"→ {len(posts)} new rows (comments + replies)")
    save(posts)
