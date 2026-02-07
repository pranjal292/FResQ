import sqlite3
from datetime import datetime

DB_NAME = "fresq.db"

def add_dummy_driver():
    # Credentials for the dummy driver
    phone = "9999999999"
    username = "Dummy_Express_Driver"
    
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        
        # Check if dummy already exists to avoid primary key errors
        cursor.execute("SELECT phone FROM users WHERE phone = ?", (phone,))
        if cursor.fetchone():
            print(f"Driver {phone} already exists. Updating coordinates...")
            cursor.execute('''
                UPDATE users 
                SET is_active = 1, last_lat = 25.2006, last_lon = 75.9023 
                WHERE phone = ?
            ''', (phone,))
        else:
            # Insert new active driver at the specified coordinates
            cursor.execute('''
                INSERT INTO users (phone, username, password, is_active, last_lat, last_lon)
                VALUES (?, ?, 'dummy_pass', 1, 25.2006, 75.9023)
            ''', (phone, username))
        
        conn.commit()
    print(f"✅ Dummy driver '{username}' added at 25.2006, 75.9023")

if __name__ == "__main__":
    add_dummy_driver()