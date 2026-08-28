#!/usr/bin/env python3
"""
Comprehensive script to fix all remaining species name issues in the database.
Finds all records where Sci_Name = Com_Name and attempts to look them up.
"""

import os
import sqlite3
import json

DB_PATH = os.path.expanduser('~/BirdNET-Pi/scripts/birds.db')
LABELS_EN_PATH = os.path.expanduser('~/BirdNET-Pi/model/l18n/labels_en.json')

# Build reverse lookup from English labels
def load_english_labels():
    """Load English labels and build a reverse lookup"""
    reverse_map = {}
    try:
        with open(LABELS_EN_PATH, 'r') as f:
            labels = json.load(f)
            for sci_name, eng_name in labels.items():
                reverse_map[eng_name] = sci_name
        print(f"✓ Loaded {len(reverse_map)} English species mappings")
        return reverse_map
    except Exception as e:
        print(f"ERROR loading labels: {e}")
        return {}


def main():
    # Load the English labels
    english_labels = load_english_labels()
    
    if not english_labels:
        print("ERROR: Could not load English labels")
        return
    
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        
        # Find all records where Sci_Name = Com_Name
        cur.execute("SELECT DISTINCT Sci_Name, Com_Name FROM detections WHERE Sci_Name = Com_Name")
        problematic_species = cur.fetchall()
        
        if not problematic_species:
            print("✓ No problematic species found (Sci_Name = Com_Name)")
            con.close()
            return
        
        print(f"\nFound {len(problematic_species)} problematic species:\n")
        
        total_fixed = 0
        
        for sci_name, com_name in problematic_species:
            # Try to find the correct scientific name in the English labels
            if com_name in english_labels:
                correct_sci_name = english_labels[com_name]
                
                # Count records to fix
                cur.execute("SELECT COUNT(*) FROM detections WHERE Sci_Name = ? AND Com_Name = ?", 
                           (sci_name, com_name))
                count = cur.fetchone()[0]
                
                print(f"  Fixing {count:5} records: '{com_name}' -> '{correct_sci_name}'")
                
                # Update the records
                cur.execute("UPDATE detections SET Sci_Name = ? WHERE Sci_Name = ? AND Com_Name = ?",
                           (correct_sci_name, sci_name, com_name))
                total_fixed += count
        
        con.commit()
        
        if total_fixed > 0:
            print(f"\n✓ Successfully fixed {total_fixed} additional records")
            
            # Show final status
            cur.execute("SELECT COUNT(*) FROM detections WHERE Sci_Name = Com_Name")
            remaining = cur.fetchone()[0]
            if remaining > 0:
                print(f"⚠️  {remaining} records still have Sci_Name = Com_Name (species not in English labels)")
        else:
            print("No records needed fixing")
        
        con.close()
        
    except Exception as e:
        print(f"ERROR: {e}")


if __name__ == '__main__':
    main()
