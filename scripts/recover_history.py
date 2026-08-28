#!/usr/bin/env python3
"""
Recovery script to rebuild the bird detection database from existing extracted files.
This script scans the BirdSongs/Extracted directory structure and repopulates the database.

It first checks for BirdDB.txt backup file to get accurate scientific names.

Usage:
    python3 recover_history.py [--dry-run]

Options:
    --dry-run  : Show what would be imported without actually modifying the database
"""

import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Configuration
HOME_DIR = Path.home()
BIRDNET_ROOT_CANDIDATES = [
    HOME_DIR / 'BirdNET-Pi',
    Path('/home/birdnet/BirdNET-Pi'),
    Path('/home/pi/BirdNET-Pi'),
    Path('/home/avian/BirdNET-Pi'),
    Path('/home/birdnetpi/BirdNET-Pi'),
]
BIRDNET_ROOT = next((p for p in BIRDNET_ROOT_CANDIDATES if p.exists()), HOME_DIR / 'BirdNET-Pi')

EXTRACTED_DIR_CANDIDATES = [
    HOME_DIR / 'BirdSongs' / 'Extracted' / 'By_Date',
    BIRDNET_ROOT / 'BirdSongs' / 'Extracted' / 'By_Date',
]
EXTRACTED_DIR = next((p for p in EXTRACTED_DIR_CANDIDATES if p.exists()), EXTRACTED_DIR_CANDIDATES[0])

DB_PATH = BIRDNET_ROOT / 'scripts' / 'birds.db'
LABELS_FILE_CANDIDATES = [
    BIRDNET_ROOT / 'model' / 'labels.txt',
    BIRDNET_ROOT / 'model' / 'BirdNET_GLOBAL_6K_V2.4_Model_FP16_Labels.txt',
    BIRDNET_ROOT / 'model' / 'BirdNET_6K_GLOBAL_MODEL_Labels.txt',
    BIRDNET_ROOT / 'model' / 'BirdNET_GLOBAL_6K_V2.4_MData_Model_FP16_Labels.txt',
]
LABELS_FILE = next((p for p in LABELS_FILE_CANDIDATES if p.exists()), LABELS_FILE_CANDIDATES[0])
BIRDDB_BACKUP = BIRDNET_ROOT / 'BirdDB.txt'

# Default values (will be read from config if available)
LATITUDE = -1
LONGITUDE = -1
CUTOFF = 0.7
SENSITIVITY = 1.25
OVERLAP = 0.0

# Species name mapping cache (Com_Name -> Sci_Name)
SPECIES_MAP = {}


def parse_directory_structure():
    """
    Parse the BirdSongs/Extracted/By_Date directory structure.
    Expected structure: By_Date/{YYYY-MM-DD}/{Common_Name}/{extracted_file_name}
    
    Returns: List of tuples (date, species_info, file_name)
    """
    detections = []
    if not os.path.exists(EXTRACTED_DIR):
        print(f"ERROR: Extracted directory not found: {EXTRACTED_DIR}")
        return detections
    
    # Walk through date directories
    for date_dir in sorted(os.listdir(EXTRACTED_DIR)):
        date_path = os.path.join(EXTRACTED_DIR, date_dir)
        
        # Validate date format YYYY-MM-DD
        if not os.path.isdir(date_path):
            continue
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_dir):
            print(f"WARNING: Skipping invalid date directory: {date_dir}")
            continue
        
        # Walk through species directories
        for species_dir in sorted(os.listdir(date_path)):
            species_path = os.path.join(date_path, species_dir)
            
            if not os.path.isdir(species_path):
                continue
            
            # Parse species name (Common_Name format with underscores instead of spaces)
            common_name = species_dir.replace('_', ' ')
            
            # Walk through extracted files
            for extracted_file in sorted(os.listdir(species_path)):
                if not extracted_file.endswith(('.wav', '.mp3')):
                    continue
                
                # Parse time from filename if possible
                # Typical format: Common_Name-XX-YYYY-MM-DD-user-HH:MM:SS.mp3
                time_match = re.search(r'-(\d{2}):(\d{2}):(\d{2})', extracted_file)
                if time_match:
                    time_str = f"{time_match.group(1)}:{time_match.group(2)}:{time_match.group(3)}"
                else:
                    time_str = "12:00:00"  # Default time if not found
                
                detections.append({
                    'date': date_dir,
                    'time': time_str,
                    'common_name': common_name,
                    'file_name': extracted_file,
                    'full_path': os.path.join(species_path, extracted_file)
                })
    
    return detections


def get_config_values():
    """Try to read configuration values from birdnet.conf"""
    global LATITUDE, LONGITUDE, CUTOFF, SENSITIVITY, OVERLAP
    
    conf_path = '/etc/birdnet/birdnet.conf'
    if os.path.exists(conf_path):
        try:
            with open(conf_path, 'r') as f:
                for line in f:
                    if line.startswith('LATITUDE='):
                        LATITUDE = float(line.split('=')[1].strip())
                    elif line.startswith('LONGITUDE='):
                        LONGITUDE = float(line.split('=')[1].strip())
                    elif line.startswith('CONFIDENCE='):
                        CUTOFF = float(line.split('=')[1].strip())
                    elif line.startswith('SENSITIVITY='):
                        SENSITIVITY = float(line.split('=')[1].strip())
                    elif line.startswith('OVERLAP='):
                        OVERLAP = float(line.split('=')[1].strip())
            print(f"✓ Loaded config: LAT={LATITUDE}, LON={LONGITUDE}")
        except Exception as e:
            print(f"WARNING: Could not parse config file: {e}")


def load_species_mapping():
    """Load the species name mapping from labels.txt"""
    global SPECIES_MAP
    
    if not os.path.exists(LABELS_FILE):
        print(f"WARNING: Labels file not found: {LABELS_FILE}")
        return
    
    try:
        with open(LABELS_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # Format: Sci_Name_Common_Name
                # Split by the last underscore to separate sci name from common name
                parts = line.rsplit('_', 1)
                if len(parts) == 2:
                    sci_name = parts[0]
                    com_name = parts[1]
                    # Store with both underscore and space versions of common name
                    SPECIES_MAP[com_name.replace(' ', '_')] = sci_name
                    SPECIES_MAP[com_name] = sci_name
        print(f"✓ Loaded {len(SPECIES_MAP)} species mappings from labels file")
    except Exception as e:
        print(f"WARNING: Could not parse labels file: {e}")


def load_species_from_birddb():
    """Load species mappings from BirdDB.txt backup file"""
    global SPECIES_MAP
    
    if not os.path.exists(BIRDDB_BACKUP):
        return
    
    try:
        with open(BIRDDB_BACKUP, 'r') as f:
            first_line = True
            for line in f:
                if first_line:
                    # Skip header line
                    first_line = False
                    continue
                
                line = line.strip()
                if not line:
                    continue
                
                # Format: Date;Time;Sci_Name;Com_Name;Confidence;Lat;Lon;Cutoff;Week;Sens;Overlap
                parts = line.split(';')
                if len(parts) >= 4:
                    sci_name = parts[2]
                    com_name = parts[3]
                    # Store with both underscore and space versions
                    SPECIES_MAP[com_name] = sci_name
                    SPECIES_MAP[com_name.replace(' ', '_')] = sci_name
        
        print(f"✓ Enhanced species mapping with {len(SPECIES_MAP)} entries from BirdDB.txt")
    except Exception as e:
        print(f"WARNING: Could not parse BirdDB.txt: {e}")


def build_english_scientific_mapping():
    """Build a mapping of English common names to scientific names from labels.txt"""
    global SPECIES_MAP
    
    # This is a reverse engineering approach: we'll try to guess English names from the pattern
    # by using the fact that labels.txt has Sci_Name_Dutch_Name format
    # and we know some English names from the extracted directories
    
    # Manual mapping for common species (can be extended)
    manual_map = {
        'Black Redstart': 'Phoenicurus ochruros',
        'Carrion Crow': 'Corvus corone',
        'Common Chiffchaff': 'Phylloscopus collybita',
        'Common House-Martin': 'Delichon urbicum',
        'Common Kingfisher': 'Alcedo atthis',
        'Common Raven': 'Corvus corax',
        'Common Swift': 'Apus apus',
        'Common Wood-Pigeon': 'Columba palumbus',
        'Dunlin': 'Calidris alpina',
        'Dunnock': 'Prunella modularis',
        'Eurasian Blackbird': 'Turdus merula',
        'Eurasian Blackcap': 'Sylvia atricapilla',
        'Eurasian Blue Tit': 'Cyanistes caeruleus',
        'Eurasian Bullfinch': 'Pyrrhula pyrrhula',
        'Eurasian Collared-Dove': 'Streptopelia decaocto',
        'Eurasian Coot': 'Fulica atra',
        'Eurasian Curlew': 'Numenius arquata',
        'Eurasian Golden Oriole': 'Oriolus oriolus',
        'Eurasian Green Woodpecker': 'Picus viridis',
        'Eurasian Jackdaw': 'Corvus monedula',
        'Eurasian Linnet': 'Linaria cannabina',
        'Eurasian Magpie': 'Pica pica',
        'Eurasian Moorhen': 'Gallinula chloropus',
        'Eurasian Skylark': 'Alauda arvensis',
        'Eurasian Wren': 'Troglodytes troglodytes',
        'European Goldfinch': 'Carduelis carduelis',
        'European Robin': 'Erithacus rubecula',
        'European Stonechat': 'Saxicola rubicola',
        'Gadwall': 'Anas strepera',
        'Gray Heron': 'Ardea cinerea',
        'Gray Wagtail': 'Motacilla cinerea',
        'Graylag Goose': 'Anser anser',
        'Great Spotted Woodpecker': 'Dendrocopos major',
        'Great Tit': 'Parus major',
        'Green-winged Teal': 'Anas crecca',
        'Hawfinch': 'Coccothraustes coccothraustes',
        'Long-tailed Tit': 'Aegithalos caudatus',
        'Marsh Tit': 'Poecile palustris',
        'Mute Swan': 'Cygnus olor',
        'Rock Pigeon': 'Columba livia',
        'Water Rail': 'Rallus aquaticus',
    }
    
    # Add all variations to the map
    for eng_name, sci_name in manual_map.items():
        SPECIES_MAP[eng_name] = sci_name
        SPECIES_MAP[eng_name.replace(' ', '_')] = sci_name
    
    print(f"✓ Added {len(manual_map)} manual species mappings for English names")


def extract_scientific_name(common_name):
    """
    Look up scientific name from the species mapping.
    Falls back to common name if not found.
    """
    # Try exact match first
    if common_name in SPECIES_MAP:
        return SPECIES_MAP[common_name]
    
    # Try with underscores converted to spaces
    if common_name.replace('_', ' ') in SPECIES_MAP:
        return SPECIES_MAP[common_name.replace('_', ' ')]
    
    # Try with spaces converted to underscores
    if common_name.replace(' ', '_') in SPECIES_MAP:
        return SPECIES_MAP[common_name.replace(' ', '_')]
    
    # If not found, return the common name as a fallback
    return common_name


def recover_database(detections, dry_run=False):
    """
    Repopulate the database with detected records.
    """
    if dry_run:
        print("\n" + "="*80)
        print("DRY RUN - No changes will be made to the database")
        print("="*80 + "\n")

    db_path = str(DB_PATH)

    if not detections:
        print("ERROR: No detections found to recover!")
        return

    if not os.path.exists(db_path):
        print(f"ERROR: Database not found at {db_path}")
        print("The BirdNET-Pi install may be in a different directory or the service may not have been initialized yet.")
        return
    
    print(f"Found {len(detections)} detection records to restore\n")
    
    if not dry_run:
        # Ensure database exists and has the correct schema
        try:
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            
            # Check if detections table exists
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='detections'")
            if not cur.fetchone():
                print("ERROR: Detections table not found. Please run createdb.sh first.")
                con.close()
                return
            
            con.close()
        except Exception as e:
            print(f"ERROR: Could not connect to database: {e}")
            return
    
    # Process each detection
    successful = 0
    skipped = 0
    errors = 0
    
    for detection in detections:
        try:
            # Extract confidence from file metadata if possible (default to 0.7)
            confidence = CUTOFF
            sci_name = extract_scientific_name(detection['common_name'])
            
            if dry_run:
                print(f"  {detection['date']} {detection['time']} | "
                      f"{detection['common_name']:30} | {sci_name:30} | {detection['file_name']}")
            else:
                con = sqlite3.connect(DB_PATH)
                cur = con.cursor()
                
                # Check if this record already exists
                cur.execute("SELECT COUNT(*) FROM detections WHERE Date=? AND Time=? AND File_Name=?",
                           (detection['date'], detection['time'], detection['file_name']))
                if cur.fetchone()[0] > 0:
                    skipped += 1
                    con.close()
                    continue
                
                # Insert the detection record
                week = datetime.strptime(detection['date'], '%Y-%m-%d').isocalendar()[1]
                cur.execute(
                    "INSERT INTO detections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (detection['date'], detection['time'], sci_name, detection['common_name'],
                     confidence, LATITUDE, LONGITUDE, CUTOFF, week, SENSITIVITY, OVERLAP,
                     detection['file_name'])
                )
                con.commit()
                con.close()
                successful += 1
        
        except Exception as e:
            print(f"ERROR processing {detection['file_name']}: {e}")
            errors += 1
    
    print("\n" + "="*80)
    if dry_run:
        print(f"DRY RUN SUMMARY:")
        print(f"  Records that would be imported: {len(detections)}")
    else:
        print(f"RECOVERY COMPLETE:")
        print(f"  Successfully imported: {successful}")
        print(f"  Skipped (already exist): {skipped}")
        print(f"  Errors: {errors}")
    print("="*80 + "\n")


def main():
    dry_run = '--dry-run' in sys.argv

    print("Bird Detection History Recovery Tool")
    print("="*80)
    print(f"BirdNET-Pi root: {BIRDNET_ROOT}")
    print(f"Database: {DB_PATH}")
    print(f"Extracted files dir: {EXTRACTED_DIR}")
    print(f"Labels file: {LABELS_FILE}")
    print(f"Backup file: {BIRDDB_BACKUP}\n")

    # Get config values
    get_config_values()
    
    # Load species mapping from labels
    load_species_mapping()
    
    # Try to enhance mapping from backup file
    load_species_from_birddb()
    
    # Add English to scientific name mappings
    build_english_scientific_mapping()
    
    # Parse directory structure
    print("Scanning for extracted recordings...")
    detections = parse_directory_structure()
    
    if not detections:
        print("ERROR: No recordings found in the extracted directory!")
        print(f"Please check that {EXTRACTED_DIR} exists and contains recordings.")
        return
    
    # Recover database
    recover_database(detections, dry_run=dry_run)
    
    if dry_run:
        print("To perform the actual recovery, run:")
        print("  python3 recover_history.py")


if __name__ == '__main__':
    main()
