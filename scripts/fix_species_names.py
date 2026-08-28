#!/usr/bin/env python3
"""
Script to fix bird species names in the database.
This fixes records where the Sci_Name is actually an English common name,
and updates it to the correct scientific name.

Usage:
    python3 fix_species_names.py
"""

import os
import sqlite3

DB_PATH = os.path.expanduser('~/BirdNET-Pi/scripts/birds.db')

# Mapping of incorrect Sci_Name (English common name) to correct scientific name
FIXES = {
    'Common Chiffchaff': 'Phylloscopus collybita',
    'Eurasian Blackcap': 'Sylvia atricapilla',
    'Eurasian Coot': 'Fulica atra',
    'Eurasian Skylark': 'Alauda arvensis',
    'Eurasian Wren': 'Troglodytes troglodytes',
    'European Goldfinch': 'Carduelis carduelis',
    'European Robin': 'Erithacus rubecula',
    'European Stonechat': 'Saxicola rubicola',
    'Gray Heron': 'Ardea cinerea',
    'Gray Wagtail': 'Motacilla cinerea',
    'Great Spotted Woodpecker': 'Dendrocopos major',
    'Hawfinch': 'Coccothraustes coccothraustes',
    'Long-tailed Tit': 'Aegithalos caudatus',
}


def main():
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        
        total_fixed = 0
        
        for incorrect_name, correct_sci_name in FIXES.items():
            # Check how many records need fixing
            cur.execute("SELECT COUNT(*) FROM detections WHERE Sci_Name = ?", (incorrect_name,))
            count = cur.fetchone()[0]
            
            if count > 0:
                print(f"Fixing {count} records: '{incorrect_name}' -> '{correct_sci_name}'")
                cur.execute("UPDATE detections SET Sci_Name = ? WHERE Sci_Name = ?", 
                           (correct_sci_name, incorrect_name))
                total_fixed += count
        
        con.commit()
        
        print(f"\n✓ Successfully fixed {total_fixed} records")
        
        # Show a sample of the fixed data
        print("\nSample of corrected records:")
        cur.execute("SELECT DISTINCT Sci_Name, Com_Name FROM detections WHERE Sci_Name IN (?, ?, ?, ?) LIMIT 10",
                   (FIXES[list(FIXES.keys())[0]], FIXES[list(FIXES.keys())[1]], 
                    FIXES[list(FIXES.keys())[2]], FIXES[list(FIXES.keys())[3]]))
        for row in cur.fetchall():
            print(f"  {row[0]} | {row[1]}")
        
        con.close()
        
    except Exception as e:
        print(f"ERROR: {e}")


if __name__ == '__main__':
    main()
