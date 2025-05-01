from flask import Flask, request, render_template, request, session, redirect, url_for
from openai import OpenAI
from dotenv import load_dotenv
import os
import mysql.connector

load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=api_key)
app = Flask(__name__)
app.secret_key = "1234"

db = mysql.connector.connect(
    host=os.getenv("DB_HOST"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_NAME")
)
cursor = db.cursor()

def get_response(history, prompt):
    messages = [{"role": "system", "content": "You are a helpful assistant and add emojis to the responses.Give 2 lines answers to the questions."}]
    
    for msg in history:
        messages.append({"role": "user", "content": msg["user"]})
        messages.append({"role": "assistant", "content": msg["bot"]})

    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model="gpt-4o-mini",  
        messages=messages
    )
    return response.choices[0].message.content.strip()

@app.route("/", methods=["GET", "POST"])
def home():
    if "chat_history" not in session:
        session["chat_history"] = []

    if request.method == "POST":
        user_input = request.form["user_input"].strip()

        # Quit command resets session
        if user_input.lower() == "quit":
            session.clear()
            cursor.execute("DELETE FROM chat_history")
            db.commit()
            return redirect(url_for("home"))

        bot_response = get_response(session["chat_history"], user_input)

        # Save the current interaction
        session["chat_history"].append({"user": user_input, "bot": bot_response})
        session.modified = True

    return render_template("index.html", chat_history=session.get("chat_history", []))

if __name__ == "__main__":
    app.run(debug=True)