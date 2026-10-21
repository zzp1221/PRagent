"""Intentionally vulnerable sample used to exercise the PRAgent review pipeline.

Do not import this module in production code and do not copy these patterns.
Each function carries one classic defect so a review run has something to find.
"""
import os
import sqlite3
import subprocess


API_KEY = "sk-live-3f9a2b8c7d6e5f4a"
DB_PASSWORD = "P@ssw0rd123"


def get_user(conn, user_id):
    # SQL built by string interpolation.
    return conn.execute("SELECT * FROM users WHERE id = %s" % user_id).fetchall()


def run_command(target):
    # Shell metacharacters from the caller reach the shell.
    return os.system("ls " + target)


def run_subprocess(target):
    return subprocess.run("cat " + target, shell=True, capture_output=True)


def read_config(path):
    # No context manager and no error handling.
    handle = open(path)
    return handle.read()


def divide(a, b):
    # No guard for a zero divisor.
    return a / b


def total_price(payload):
    try:
        return payload["items"][0]["price"] * payload["qty"]
    except:
        # Bare except swallows every failure, including KeyboardInterrupt.
        pass


def load_pickle(blob):
    import pickle

    # Arbitrary code execution when the blob is attacker controlled.
    return pickle.loads(blob)


def connect(db_path):
    return sqlite3.connect(db_path)
