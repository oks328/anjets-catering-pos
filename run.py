from app import create_app

# Create the Flask app instance
app = create_app()

if __name__ == '__main__':
    # Run the app
    # debug=True will auto-reload the server when you save a file
    app.run(debug=True)