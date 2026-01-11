#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.8"
# dependencies = [
#     "pandas",
#     "feedparser",
#     "guessit",
#     "thefuzz[speed]",
#     "requests",
# ]
# ///

import json
import logging
import time
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import requests
from guessit import guessit
from thefuzz import fuzz

# --- Configuration ---
# Input JSON file containing anime metadata.
METADATA_FILE = 'multibox_assets/metadata.json'
# The name for the output file with the torrent URLs.
OUTPUT_FILE = 'torrent_urls.txt'
# Base URL for Nyaa RSS feeds. The query will be appended.
NYAA_RSS_BASE_URL = 'https://nyaa.si/?page=rss&c=1_2&f=0&q='
# A broad, generic query to find recent episode 1 releases.
# This helps find many matches with a single initial request.
BROAD_SEARCH_QUERY = 'subsplease 480p'
# The minimum similarity score (out of 100) to consider a torrent a match.
SIMILARITY_THRESHOLD = 85
# The delay in seconds between individual targeted Nyaa queries to be respectful to their servers.
QUERY_DELAY_SECONDS = 5
# Preferred resolutions for targeted searches, in order of preference.
RESOLUTION_PREFERENCE = ['480p', '720p', '1080p']

# Set up basic logging to show progress and status.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def fetch_and_parse_nyaa_feed(query: str) -> list[dict]:
    """
    Fetches torrents from Nyaa for a given query and parses them for episode 1 releases.

    Args:
        query: The search term to use for the Nyaa RSS feed.

    Returns:
        A list of dictionaries, each representing a parsed torrent for a first episode.
    """
    search_query = quote_plus(query)
    url = f"{NYAA_RSS_BASE_URL}{search_query}"
    logging.info(f"Fetching Nyaa feed with query: '{query}'")

    try:
        # Use a common user-agent to avoid potential HTTP 403 Forbidden errors.
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()

        feed = feedparser.parse(response.content)
        if feed.bozo:
            logging.warning(f"The RSS feed may be malformed for query '{query}'. Reason: {feed.bozo_exception}")

        torrents = []
        for entry in feed.entries:
            parsed_info = guessit(entry.title)
            # We are only interested in torrents identified as the first episode.
            if parsed_info.get('type') == 'episode' and parsed_info.get('episode') == 1:
                torrents.append({
                    'parsed_title': parsed_info.get('title'),
                    'resolution': parsed_info.get('screen_size'),
                    'url': entry.link,
                })
        logging.info(f"Found {len(torrents)} torrents that are first episodes for query '{query}'.")
        return torrents
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to fetch or read the RSS feed for query '{query}': {e}")
        return []


def find_best_match_from_list(anime_details: dict, torrent_list: list[dict]) -> str | None:
    """
    Finds the best torrent match for an anime from a pre-fetched list using fuzzy string matching.

    Args:
        anime_details: A dictionary containing the anime's 'nameRomaji' and 'nameEnglish'.
        torrent_list: A list of parsed torrents to search through.

    Returns:
        The URL of the best matching torrent, or None if no suitable match is found.
    """
    best_match_url = None
    best_score = SIMILARITY_THRESHOLD - 1
    
    romaji_title = anime_details['nameRomaji']
    english_title = anime_details.get('nameEnglish')

    for torrent in torrent_list:
        torrent_anime_title = torrent.get('parsed_title')
        if not torrent_anime_title:
            continue

        # Calculate similarity against both Romaji and English titles.
        score_romaji = fuzz.token_set_ratio(romaji_title, torrent_anime_title)
        score_english = 0
        if english_title:
            score_english = fuzz.token_set_ratio(english_title, torrent_anime_title)
        
        current_score = max(score_romaji, score_english)

        if current_score > best_score:
            best_score = current_score
            best_match_url = torrent['url']

    if best_score >= SIMILARITY_THRESHOLD:
        logging.info(f"Broad search match found for '{romaji_title}' with score {best_score}")
        return best_match_url
    
    return None


def find_best_match_targeted(anime_title: str) -> str | None:
    """
    Performs a targeted Nyaa search for a single anime title and selects the best torrent.

    Args:
        anime_title: The title of the anime to search for.

    Returns:
        The URL of the best matching torrent, or None if not found.
    """
    candidates = fetch_and_parse_nyaa_feed(anime_title)
    if not candidates:
        return None

    # Filter candidates to ensure they are a close match to the search title.
    valid_candidates = []
    for torrent in candidates:
        score = fuzz.token_set_ratio(anime_title, torrent['parsed_title'])
        if score >= SIMILARITY_THRESHOLD:
            valid_candidates.append(torrent)

    if not valid_candidates:
        logging.info(f"No valid torrents found for '{anime_title}' after similarity check.")
        return None

    # Select the best torrent based on the resolution preference.
    for res in RESOLUTION_PREFERENCE:
        for torrent in valid_candidates:
            if torrent['resolution'] == res:
                logging.info(f"Found best match for '{anime_title}': {res} version.")
                return torrent['url']

    # If no preferred resolution is found, return the first valid candidate as a fallback.
    best_fallback = valid_candidates[0]
    logging.info(f"Found a fallback match for '{anime_title}': {best_fallback['resolution'] or 'Unknown resolution'}.")
    return best_fallback['url']


def main():
    """Main script to read JSON, find torrents, and write the output file."""
    metadata_path = Path(METADATA_FILE)
    if not metadata_path.exists():
        logging.error(f"Input file not found: '{metadata_path}'. Please ensure it is in the same directory.")
        return

    # 1. Load the anime metadata from the JSON file.
    with open(metadata_path, 'r', encoding='utf-8') as f:
        metadata = json.load(f)
    all_anime = metadata.get('anime', [])
    if not all_anime:
        logging.error("Metadata file does not contain an 'anime' list.")
        return
    logging.info(f"Successfully loaded {len(all_anime)} anime from '{METADATA_FILE}'.")

    # This dictionary will store the final torrent URL for each anime, using its ID as the key.
    results = {anime['id']: None for anime in all_anime}
    
    # --- STAGE 1: Broad Search ---
    logging.info("--- Starting Stage 1: Broad Search ---")
    broad_search_torrents = fetch_and_parse_nyaa_feed(BROAD_SEARCH_QUERY)
    
    unmatched_anime = []
    if broad_search_torrents:
        for anime in all_anime:
            match_url = find_best_match_from_list(anime, broad_search_torrents)
            if match_url:
                results[anime['id']] = match_url
            else:
                unmatched_anime.append(anime)
    else:
        logging.warning("Broad search returned no torrents. Proceeding directly to targeted search for all anime.")
        unmatched_anime = all_anime
        
    found_count = len(all_anime) - len(unmatched_anime)
    logging.info(f"Broad search complete. Matched {found_count} anime. {len(unmatched_anime)} remain unmatched.")

    # --- STAGE 2: Targeted Search for remaining anime ---
    if unmatched_anime:
        logging.info("--- Starting Stage 2: Targeted Search for Unmatched Anime ---")
        for i, anime in enumerate(unmatched_anime):
            romaji_title = anime['nameRomaji']
            logging.info(f"Searching for unmatched anime ({i + 1}/{len(unmatched_anime)}): '{romaji_title}'")
            
            match_url = find_best_match_targeted(romaji_title)
            if match_url:
                results[anime['id']] = match_url
            else:
                logging.warning(f"Could not find a targeted match for '{romaji_title}'")

            # Be a good internet citizen, even on the last item.
            if i < len(unmatched_anime) - 1:
                logging.info(f"Waiting for {QUERY_DELAY_SECONDS} seconds before the next query...")
                time.sleep(QUERY_DELAY_SECONDS)

    # --- STAGE 3: Write Output File ---
    logging.info("--- Search complete. Writing results to output file. ---")
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            for anime in all_anime:
                url = results.get(anime['id'], "") # Default to empty string if not found
                f.write(f"{url or ''}\n")
        
        final_matched_count = sum(1 for url in results.values() if url is not None)
        logging.info(f"Successfully wrote results for {final_matched_count}/{len(all_anime)} anime to '{OUTPUT_FILE}'.")
    except IOError as e:
        logging.error(f"Failed to write to the output file '{OUTPUT_FILE}': {e}")


if __name__ == "__main__":
    main()
