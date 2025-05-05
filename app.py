from flask import Flask, request, render_template
from openai import OpenAI
from dotenv import load_dotenv
import os
import mysql.connector

# Load environment variables
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=api_key)
app = Flask(__name__)
app.secret_key = "1234"

# MySQL connection
db = mysql.connector.connect(
    host=os.getenv("DB_HOST"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_NAME")
)
cursor = db.cursor(dictionary=True)

# Get response from OpenAI
def get_response(history, prompt):
    messages = [{"role": "system", "content": "You are a helpful assistant and add emojis to the responses. Give 2 lines answers to the questions."}]
    for chat in history:
        messages.append({"role": "user", "content": chat["user_message"]})
        messages.append({"role": "assistant", "content": chat["bot_response"]})
    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages
    )
    return response.choices[0].message.content.strip()

@app.route("/", methods=["GET", "POST"])
def home():
    search_query = request.args.get("search", "").strip()

    if request.method == "POST":
        user_input = request.form["user_input"].strip()

        cursor.execute("SELECT * FROM chat_history")
        history = cursor.fetchall()

        bot_response = get_response(history, user_input)
        cursor.execute("INSERT INTO chat_history (user_message, bot_response) VALUES (%s, %s)", (user_input, bot_response))
        db.commit()
        return render_template("index.html", chat_history=history + [{"user_message": user_input, "bot_response": bot_response}], search_query="")

    if search_query:
        cursor.execute("SELECT * FROM chat_history WHERE user_message LIKE %s OR bot_response LIKE %s", 
                       (f"%{search_query}%", f"%{search_query}%"))
    else:
        cursor.execute("SELECT * FROM chat_history")

    chat_history = cursor.fetchall()
    return render_template("index.html", chat_history=chat_history, search_query=search_query)

if __name__ == "__main__":
    app.run(debug=True)
