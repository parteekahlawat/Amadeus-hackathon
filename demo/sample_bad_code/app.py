"""Sample travel booking app with intentional vulnerabilities for demo."""

from flask import Flask, request, jsonify, render_template_string
import sqlite3
import os
import requests

app = Flask(__name__)

# A02: Hardcoded secret
DATABASE_PASSWORD = "admin123"
API_KEY = "sk-groq-1234567890abcdef"

def get_db():
    return sqlite3.connect("bookings.db")


@app.route("/api/v2/pricing", methods=["POST"])
def get_pricing():
    # A03: SQL Injection
    destination = request.json.get("destination")
    query = f"SELECT price FROM flights WHERE destination = '{destination}'"
    db = get_db()
    result = db.execute(query).fetchone()
    return jsonify({"price": result[0] if result else 0})


@app.route("/search")
def search():
    # A03 + LLM01: User input passed directly to LLM prompt
    query = request.args.get("q", "")
    prompt = f"Find travel deals for: {query}"
    response = requests.post("https://api.groq.com/v1/completions", json={
        "prompt": prompt,
        "model": "llama-3.1-70b"
    }, headers={"Authorization": f"Bearer {API_KEY}"})

    # LLM02: LLM output rendered without sanitization
    result = response.json().get("choices", [{}])[0].get("text", "")
    return render_template_string(f"<div>{result}</div>")


@app.route("/checkout", methods=["POST"])
def checkout():
    # A05: No CSRF protection
    # A07: No authentication check
    booking_data = request.json
    db = get_db()
    db.execute(
        "INSERT INTO bookings (user_id, flight_id, payment) VALUES (?, ?, ?)",
        (booking_data["user_id"], booking_data["flight_id"], booking_data["payment"])
    )
    db.commit()
    return jsonify({"status": "booked"})


@app.route("/proxy")
def proxy():
    # A10: SSRF — unvalidated URL
    url = request.args.get("url")
    response = requests.get(url)
    return response.text


@app.route("/webhook", methods=["POST"])
def webhook():
    # A08: Insecure deserialization
    import pickle
    data = pickle.loads(request.data)
    return jsonify({"processed": True})


if __name__ == "__main__":
    app.run(debug=True)  # A05: Debug mode in production
