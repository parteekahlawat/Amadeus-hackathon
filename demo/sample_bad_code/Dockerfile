FROM python:3.12-slim
WORKDIR /app
RUN pip install flask requests
COPY app.py .
COPY templates/ templates/
RUN mkdir -p static && touch static/hero.jpg
RUN python -c "import sqlite3; db=sqlite3.connect('bookings.db'); db.execute('CREATE TABLE IF NOT EXISTS flights (destination TEXT, price REAL)'); db.execute('CREATE TABLE IF NOT EXISTS bookings (user_id TEXT, flight_id TEXT, payment TEXT)'); db.execute(\"INSERT INTO flights VALUES ('Paris', 599.99)\"); db.execute(\"INSERT INTO flights VALUES ('Tokyo', 1299.99)\"); db.commit()"
EXPOSE 8080
CMD ["python", "-c", "from app import app; app.run(host='0.0.0.0', port=8080, debug=True)"]
