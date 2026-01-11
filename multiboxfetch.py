import csv
import json
import math
import os
import time
import requests
from PIL import Image

# --- Configuration ---
CSV_FILE_PATH = 'multiboxwinter2026.csv'
IMAGE_CACHE_DIR = 'image_cache'
OUTPUT_DIR = 'multibox_assets'
ATLAS_MAX_WIDTH = 2048
ATLAS_MAX_HEIGHT = 2048
OUTPUT_ATLAS_NAME = 'posters.png'
OUTPUT_METADATA_NAME = 'metadata.json'
ANILIST_API_URL = 'https://graphql.anilist.co'
API_BATCH_SIZE = 30
API_RATE_LIMIT_DELAY = 1.0

# --- AniList GraphQL Query ---
MEDIA_FIELDS_QUERY = """
    id
    title {
      romaji
      english
      native
    }
    coverImage {
      extraLarge
    }
    description(asHtml: false)
    genres
    source(version: 3)
    studios(isMain: true) {
      nodes {
        id
        name
      }
    }
"""

def fetch_anilist_metadata_batch(id_batch):
    """
    Fetches detailed metadata for a batch of anime IDs in a single API call.
    """
    query_parts = [f"a{id}: Media(id: {id}, type: ANIME) {{ {MEDIA_FIELDS_QUERY} }}" for id in id_batch]
    full_query = "query { " + " ".join(query_parts) + " }"

    try:
        response = requests.post(
            ANILIST_API_URL,
            json={'query': full_query},
            headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        
        if 'errors' in data:
            print(f"  -> API Error for batch: {data['errors'][0]['message']}")
            return []
        
        media_data = data.get('data', {})
        return [obj for obj in media_data.values() if obj is not None]

    except requests.exceptions.RequestException as e:
        print(f"  -> Network Error fetching batch: {e}")
        return []

def download_image(url, anilist_id):
    """
    Downloads an image from a URL and saves it to the cache directory.
    """
    if not os.path.exists(IMAGE_CACHE_DIR): os.makedirs(IMAGE_CACHE_DIR)
    file_extension = os.path.splitext(url)[1].split('?')[0]
    local_path = os.path.join(IMAGE_CACHE_DIR, f"{anilist_id}{file_extension or '.jpg'}")

    if not os.path.exists(local_path):
        try:
            print(f"  -> Downloading poster: {url}")
            headers = {'User-Agent': 'VRChat-Multibox-Asset-Builder/1.0'}
            response = requests.get(url, stream=True, timeout=15, headers=headers)
            response.raise_for_status()
            with open(local_path, 'wb') as f: f.write(response.content)
        except requests.exceptions.RequestException as e:
            print(f"  -> Error downloading {url}: {e}")
            return None
    
    return local_path

def create_atlas_and_metadata():
    """
    Main function to drive the process of fetching data, creating the atlas,
    and generating the final metadata file while preserving CSV order.
    """
    if not os.path.exists(OUTPUT_DIR): os.makedirs(OUTPUT_DIR)

    # --- 1. Read AniList IDs from the source CSV to establish canonical order ---
    print("--- Step 1: Reading AniList IDs to establish canonical order ---")
    ordered_anilist_ids = []
    try:
        with open(CSV_FILE_PATH, mode='r', encoding='utf-8') as infile:
            for line in infile:
                line = line.strip()
                if line and line.startswith('https://anilist.co/anime/'):
                    # Extract ID from URL format: https://anilist.co/anime/198374/...
                    parts = line.split('/')
                    if len(parts) >= 5 and parts[4].isdigit():
                        ordered_anilist_ids.append(int(parts[4]))
    except FileNotFoundError:
        print(f"Error: The file '{CSV_FILE_PATH}' was not found.")
        return
        
    print(f"Found {len(ordered_anilist_ids)} IDs in the specified order.")
    # Create a map from ID to its original index for re-sorting later
    id_to_original_index = {anilist_id: i for i, anilist_id in enumerate(ordered_anilist_ids)}

    # --- 2. Fetch rich data from AniList API in batches ---
    print("\n--- Step 2: Fetching detailed metadata from AniList API ---")
    id_batches = [ordered_anilist_ids[i:i + API_BATCH_SIZE] for i in range(0, len(ordered_anilist_ids), API_BATCH_SIZE)]
    # Use a placeholder list to reconstruct the original order
    ordered_api_data = [None] * len(ordered_anilist_ids)
    
    for i, batch in enumerate(id_batches):
        print(f"Fetching batch {i+1} of {len(id_batches)} ({len(batch)} IDs)...")
        batch_results = fetch_anilist_metadata_batch(batch)
        # Place results into their correct ordered slots
        for anime_object in batch_results:
            original_index = id_to_original_index.get(anime_object['id'])
            if original_index is not None:
                ordered_api_data[original_index] = anime_object
        
        if i < len(id_batches) - 1: time.sleep(API_RATE_LIMIT_DELAY)

    # Filter out any IDs that failed to fetch
    final_ordered_data = [data for data in ordered_api_data if data is not None]
    print(f"Successfully fetched and ordered data for {len(final_ordered_data)} anime.")

    # --- 3. Download posters and get image properties ---
    print("\n--- Step 3: Processing posters based on the established order ---")
    processed_anime_info = []
    for anime_data in final_ordered_data:
        anilist_id = anime_data.get('id')
        poster_url = anime_data.get('coverImage', {}).get('extraLarge')
        romaji_title = anime_data.get('title', {}).get('romaji', f"ID {anilist_id}")

        if not poster_url:
            print(f"Skipping '{romaji_title}' due to missing poster URL.")
            continue
        
        print(f"Processing '{romaji_title}'...")
        image_path = download_image(poster_url, anilist_id)
        if image_path:
            try:
                with Image.open(image_path) as img:
                    width, height = img.size
                    processed_anime_info.append({
                        'path': image_path,
                        'original_aspect_ratio': width / height if height > 0 else 1.0,
                        'api_data': anime_data
                    })
            except (IOError, SyntaxError) as e:
                print(f"Could not open image: {image_path}. Error: {e}")

    # --- 4. Create atlas and final metadata in the correct order ---
    print("\n--- Step 4: Building atlas and metadata.json in order ---")
    num_images = len(processed_anime_info)
    if num_images == 0: return

    grid_cols = math.ceil(math.sqrt(num_images))
    grid_rows = math.ceil(num_images / grid_cols)
    cell_width = ATLAS_MAX_WIDTH // grid_cols
    cell_height = ATLAS_MAX_HEIGHT // grid_rows
    
    atlas = Image.new('RGBA', (ATLAS_MAX_WIDTH, ATLAS_MAX_HEIGHT), (0, 0, 0, 0))
    final_metadata = {"anime": []}

    # The `processed_anime_info` list is now already in the correct order
    for i, info in enumerate(processed_anime_info):
        row, col = i // grid_cols, i % grid_cols
        pos_x, pos_y = col * cell_width, row * cell_height

        with Image.open(info['path']) as img:
            resized_img = img.resize((cell_width, cell_height), Image.Resampling.LANCZOS)
            atlas.paste(resized_img, (pos_x, pos_y))

        api_data = info['api_data']
        studios = [node['name'] for node in api_data.get('studios', {}).get('nodes', [])]
        
        entry_metadata = {
            "id": api_data.get('id'),
            "videoId": str(api_data.get('id')),
            "nameRomaji": api_data.get('title', {}).get('romaji'),
            "nameEnglish": api_data.get('title', {}).get('english'),
            "description": api_data.get('description', 'No description available.'),
            "genres": api_data.get('genres', []),
            "source": (api_data.get('source') or 'UNKNOWN').replace('_', ' ').title(),
            "studio": ", ".join(studios) or "Unknown",
            "atlasX": pos_x,
            "atlasY": pos_y,
            "atlasWidth": cell_width,
            "atlasHeight": cell_height,
            "originalAspectRatio": info['original_aspect_ratio']
        }
        final_metadata["anime"].append(entry_metadata)
    
    # --- 5. Save the final files ---
    print("\n--- Step 5: Saving final asset files ---")
    atlas_path = os.path.join(OUTPUT_DIR, OUTPUT_ATLAS_NAME)
    atlas.save(atlas_path)
    print(f"Atlas image saved to: {atlas_path}")

    metadata_path = os.path.join(OUTPUT_DIR, OUTPUT_METADATA_NAME)
    # CRITICAL: Remove the alphabetical sort to preserve the original CSV order.
    # final_metadata["anime"].sort(key=lambda x: (x['nameRomaji'] or "").lower()) # This line is now removed.
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(final_metadata, f, indent=2, ensure_ascii=False)
    print(f"Metadata JSON saved to: {metadata_path}")


if __name__ == '__main__':
    create_atlas_and_metadata()
