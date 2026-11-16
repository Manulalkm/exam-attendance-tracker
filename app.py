import csv
import os
import sqlite3
from collections import Counter
from io import StringIO
from pathlib import Path

import requests
from flask import Flask, abort, flash, g, redirect, render_template, request, send_file, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-this-local-secret")
DB_PATH = Path(__file__).resolve().parent / "attendance.db"
VALID_STATUSES = {"Present", "Absent", "Late"}


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            exam_date TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            student_id TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Absent' CHECK(status IN ('Present', 'Absent', 'Late')),
            UNIQUE(session_id, student_id)
        );
    """)
    db.commit()


def load_session(session_id):
    session = get_db().execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if session is None:
        abort(404)
    return session


def session_students(session_id):
    return get_db().execute(
        "SELECT student_id, name, status FROM students WHERE session_id = ? ORDER BY name",
        (session_id,),
    ).fetchall()


def attendance_stats(students):
    counts = Counter(student["status"] for student in students)
    total = len(students)
    return {
        "total": total,
        "present": counts["Present"],
        "absent": counts["Absent"],
        "late": counts["Late"],
        "attendance_rate": round((counts["Present"] + counts["Late"]) * 100 / total) if total else 0,
    }


@app.route("/")
def index():
    sessions = get_db().execute("SELECT * FROM sessions ORDER BY exam_date DESC, id DESC").fetchall()
    return render_template("index.html", sessions=sessions)


@app.post("/sessions")
def create_session():
    name = request.form.get("name", "").strip()
    exam_date = request.form.get("exam_date", "").strip()
    if not name or not exam_date:
        flash("Session name and exam date are required.", "error")
        return redirect(url_for("index"))
    db = get_db()
    db.execute("INSERT INTO sessions(name, exam_date) VALUES (?, ?)", (name, exam_date))
    db.commit()
    flash("Exam session created.", "success")
    return redirect(url_for("index"))


@app.route("/sessions/<int:session_id>")
def session_detail(session_id):
    session = load_session(session_id)
    students = session_students(session_id)
    return render_template("session.html", session=session, students=students,
                           stats=attendance_stats(students))


@app.post("/sessions/<int:session_id>/students")
def add_student(session_id):
    load_session(session_id)
    student_id = request.form.get("student_id", "").strip()
    name = request.form.get("name", "").strip()
    if not student_id or not name:
        flash("Student ID and name are required.", "error")
    else:
        try:
            db = get_db()
            db.execute("INSERT INTO students(session_id, student_id, name) VALUES (?, ?, ?)",
                       (session_id, student_id, name))
            db.commit()
            flash("Student added.", "success")
        except sqlite3.IntegrityError:
            flash("That student ID is already in this session.", "error")
    return redirect(url_for("session_detail", session_id=session_id))


@app.route("/sessions/<int:session_id>/attendance")
def attendance_page(session_id):
    session = load_session(session_id)
    query = request.args.get("q", "").strip()
    sql = "SELECT * FROM students WHERE session_id = ?"
    params = [session_id]
    if query:
        sql += " AND (name LIKE ? OR student_id LIKE ?)"
        params.extend([f"%{query}%", f"%{query}%"])
    sql += " ORDER BY name"
    students = get_db().execute(sql, params).fetchall()
    all_students = session_students(session_id)
    return render_template("attendance.html", session=session, students=students,
                           query=query, stats=attendance_stats(all_students))


@app.post("/sessions/<int:session_id>/status")
def update_status(session_id):
    load_session(session_id)
    student_id = request.form.get("student_id", "")
    status = request.form.get("status", "")
    if status not in VALID_STATUSES:
        flash("Invalid attendance status.", "error")
    else:
        db = get_db()
        db.execute("UPDATE students SET status = ? WHERE id = ? AND session_id = ?",
                   (status, student_id, session_id))
        db.commit()
        flash("Attendance updated.", "success")
    return redirect(url_for("attendance_page", session_id=session_id, q=request.form.get("q", "")))


@app.route("/sessions/<int:session_id>/ai")
def ai_page(session_id):
    session = load_session(session_id)
    students = session_students(session_id)
    return render_template("ai.html", session=session, stats=attendance_stats(students),
                           students=students, model=os.environ.get("OLLAMA_MODEL", "llama3.2"))


@app.post("/sessions/<int:session_id>/ai/ask")
def ask_ai(session_id):
    session = load_session(session_id)
    question = request.form.get("question", "").strip()
    students = session_students(session_id)
    stats = attendance_stats(students)
    if not question:
        flash("Enter a question for the AI assistant.", "error")
        return redirect(url_for("ai_page", session_id=session_id))

    records = "\n".join(f"{s['student_id']} | {s['name']} | {s['status']}" for s in students)
    prompt = (
        "You are an assistant for exam attendance administration. Use only the data below. "
        "Do not infer grades, protected traits, or reasons for absence. If data is insufficient, say so. "
        "Be concise and do not expose information beyond the listed student IDs, names, and statuses.\n\n"
        f"Exam: {session['name']} on {session['exam_date']}\n"
        f"Totals: {stats['total']} students; {stats['present']} present; {stats['late']} late; "
        f"{stats['absent']} absent; attendance rate {stats['attendance_rate']}%.\n"
        f"Roster (ID | Name | Status):\n{records or '(No students entered)'}\n\n"
        f"Question: {question}"
    )
    ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", "llama3.2")
    try:
        response = requests.post(
            f"{ollama_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=90,
        )
        response.raise_for_status()
        answer = response.json().get("response", "").strip()
        if not answer:
            raise ValueError("The model returned an empty response.")
        return render_template("ai.html", session=session, stats=stats, students=students,
                               model=model, question=question, answer=answer)
    except (requests.RequestException, ValueError) as exc:
        flash(f"Could not reach the local AI model ({exc}). Check Ollama and the model setup in the README.", "error")
        return redirect(url_for("ai_page", session_id=session_id))


@app.route("/sessions/<int:session_id>/export")
def export_csv(session_id):
    session = load_session(session_id)
    students = session_students(session_id)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Student ID", "Name", "Status"])
    writer.writerows((s["student_id"], s["name"], s["status"]) for s in students)
    output.seek(0)
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in session["name"])
    from io import BytesIO
    buffer = BytesIO(output.getvalue().encode("utf-8-sig"))
    return send_file(buffer, mimetype="text/csv", as_attachment=True,
                     download_name=f"{safe_name}_attendance.csv")


@app.post("/sessions/<int:session_id>/delete")
def delete_session(session_id):
    load_session(session_id)
    db = get_db()
    db.execute("DELETE FROM students WHERE session_id = ?", (session_id,))
    db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    db.commit()
    flash("Session deleted.", "success")
    return redirect(url_for("index"))


@app.post("/sessions/<int:session_id>/students/<int:student_pk>/delete")
def delete_student(session_id, student_pk):
    load_session(session_id)
    db = get_db()
    db.execute("DELETE FROM students WHERE id = ? AND session_id = ?", (student_pk, session_id))
    db.commit()
    flash("Student removed.", "success")
    return redirect(url_for("session_detail", session_id=session_id))


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
