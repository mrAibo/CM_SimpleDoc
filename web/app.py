from flask import Flask, render_template

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

if __name__ == '__main__':
    # Note: Port 5000 is a common default for Flask, but might conflict
    # with other services. The subtask specifies port 5000.
    # Using 0.0.0.0 to make it accessible externally from the container.
    app.run(debug=True, host='0.0.0.0', port=5000)
