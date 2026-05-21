import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

DATABASE_URL = os.environ.get("DATABASE_URL")

def temizle():
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, data FROM signals ORDER BY (data->>'created')::timestamp ASC")
            rows = cur.fetchall()

    print(f"Toplam kayıt: {len(rows)}")

    silinecek = []
    son_giris = None
    son_created = None

    for row in rows:
        d = dict(row["data"])
        giris = d.get("giris_tl")
        created_str = d.get("created")
        rid = row["id"]

        if giris is None or created_str is None:
            continue

        giris = float(giris)
        created = datetime.strptime(created_str, "%Y-%m-%d %H:%M:%S")

        if son_created is not None:
            fark_dk = (created - son_created).total_seconds() / 60
            if fark_dk < 15:
                if son_giris - giris < 0.50:
                    silinecek.append(rid)
                    print(f"SİLİNECEK: {rid} giris={giris} onceki={son_giris} fark={son_giris-giris:.2f}")
                    continue

        son_giris = giris
        son_created = created

    print(f"Silinecek: {len(silinecek)} kayıt")

    if silinecek:
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM signals WHERE id = ANY(%s)", (silinecek,))
            conn.commit()
        print("Silindi.")
    else:
        print("Silinecek kayıt yok.")

temizle()