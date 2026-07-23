"""Seed demo data: a clean primary user and a synthetic-identity mule ring."""
import time
import db


def seed(force=False):
    db.init()
    with db._lock, db.conn() as c:
        n = c.execute("SELECT COUNT(*) FROM identities").fetchone()[0]
        if n and not force:
            return
        c.executescript("DELETE FROM identities; DELETE FROM devices; DELETE FROM links;")
        now = time.time()
        identities = [
            ("U1000", "Primary Customer (you)", "verified"),
            ("U2001", "Rahul K.", "verified"),
            ("U2002", "S. Mehta", "pending"),
            ("U2003", "A. Nair", "pending"),
            ("U3001", "Priya D.", "verified"),
            ("U3002", "Vikram S.", "verified"),
        ]
        for uid, name, kyc in identities:
            c.execute("INSERT INTO identities VALUES (?,?,?,?)", (uid, name, kyc, now))

        devices = [("DEV-7781", now, 1), ("DEV-MULE-7", now, 0), ("DEV-5520", now, 1)]
        for d in devices:
            c.execute("INSERT INTO devices VALUES (?,?,?)", d)

        # links: (user, attr_type, attr_value)
        links = [
            # primary user — own device, own payee, clean
            ("U1000", "device", "DEV-7781"),
            ("U1000", "beneficiary", "BEN-SELF-1"),
            ("U1000", "ip", "IP-203.0.113.5"),
            # mule ring: 3 accounts share one device + one payee
            ("U2001", "device", "DEV-MULE-7"),
            ("U2002", "device", "DEV-MULE-7"),
            ("U2003", "device", "DEV-MULE-7"),
            ("U2001", "beneficiary", "BEN-DROP-9"),
            ("U2002", "beneficiary", "BEN-DROP-9"),
            ("U2003", "beneficiary", "BEN-DROP-9"),
            # unrelated clean pair sharing only an IP (not a ring)
            ("U3001", "device", "DEV-5520"),
            ("U3002", "ip", "IP-198.51.100.2"),
            ("U3001", "ip", "IP-198.51.100.2"),
        ]
        for l in links:
            c.execute("INSERT INTO links VALUES (?,?,?)", l)
    return True


if __name__ == "__main__":
    seed(force=True)
    print("seeded")
