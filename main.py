import os
import time
import json
import re
import google.generativeai as genai
from flask import Flask, request, redirect, render_template, send_file
from google.cloud import storage


genai.configure(api_key=os.environ['GEMINI_API'])

BUCKET_NAME = "my-bucket-for-project"

app = Flask(__name__)

@app.route('/')
def index():
    """Displays an HTML page with uploaded files and their AI-generated descriptions."""
    files = get_list_of_files(BUCKET_NAME)
    json_files = get_json_descriptions(BUCKET_NAME)

    return render_template("index.html", files=files, json_files=json_files)

def get_json_descriptions(bucket_name):
    """Retrieves JSON descriptions for uploaded images."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blobs = bucket.list_blobs()

    json_data = {}
    for blob in blobs:
        if blob.name.endswith('.json'):
            json_string = blob.download_as_text()
            try:
                json_data[blob.name] = json.loads(json_string)
            except json.JSONDecodeError:
                json_data[blob.name] = {"title": "Error", "description": "Invalid JSON format"}
    
    return json_data


@app.route('/view/<filename>')
def view_image(filename):
    """Fetches and serves the image from GCS without exposing the public URL."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(filename)

    # Download image temporarily
    temp_path = f"/tmp/{filename}"
    blob.download_to_filename(temp_path)

    return send_file(temp_path, mimetype="image/jpeg")

@app.route('/upload', methods=["POST"])
def upload():
    """Handles file upload and processes with Gemini AI."""
    if 'form_file' not in request.files:
        return 'No file uploaded', 400

    file = request.files['form_file']
    if file.filename == '':
        return 'No selected file', 400

    filename = f"{int(time.time())}_{file.filename}"
    temp_path = os.path.join('/tmp', filename)

    file.save(temp_path)

    upload_file(BUCKET_NAME, temp_path, filename)

    description = generate_image_description(temp_path)

    json_filename = filename.replace(".jpeg", ".json").replace(".jpg", ".json")
    save_description_to_gcs(BUCKET_NAME, json_filename, description)

    os.remove(temp_path)

    return redirect("/")



def generate_image_description(image_path):
    """Uses Gemini AI to generate a JSON description for an image."""
    PROMPT = """
    Analyze the image and return a JSON response in the following format:

    {
       "title": "A concise title for the image",
       "description": "A detailed description of the image."
    }

    Ensure the response is valid JSON.
    """

    file = genai.upload_file(image_path, mime_type="image/jpeg")
    
    response = genai.GenerativeModel(model_name="gemini-1.5-flash").generate_content([file, "\n\n", PROMPT])

    print(" Raw Gemini Response:", response.text)

    try:
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            clean_json = match.group(0)
        else:
            print(" Error: No valid JSON detected in response.")
            return {
                "title": "Untitled",
                "description": "Could not generate a valid description."
            }

        data = json.loads(clean_json)

        return {
            "title": data.get("title", "Untitled"),
            "description": data.get("description", "No description available.")
        }

    except json.JSONDecodeError as e:
        print(f" JSON Decode Error: {e}")
        return {
            "title": "Untitled",
            "description": "Could not generate a valid description."
        }


def upload_file(bucket_name, source_file, destination_blob):
    """Uploads a file to Google Cloud Storage."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(destination_blob)
    blob.upload_from_filename(source_file)

def save_description_to_gcs(bucket_name, json_filename, description_data):
    """Saves the image description as a JSON file in GCS."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(json_filename)
    
    json_data = json.dumps(description_data, indent=4)
    
    blob.upload_from_string(json_data, content_type="application/json")

def get_list_of_files(bucket_name):
    """Lists all images uploaded to the GCS bucket."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blobs = bucket.list_blobs()
    
    return [blob.name for blob in blobs if blob.name.endswith(('.jpeg', '.jpg'))]


@app.route('/files/<filename>')
def display_image(filename):
    """Displays an individual image with its title and description."""
    json_filename = filename.replace('.jpeg', '.json').replace('.jpg', '.json')
    url = "https://storage.cloud.google.com"
    image_url = f"{url}/{BUCKET_NAME}/{filename}"

    storage_client = storage.Client()
    bucket = storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(json_filename)

    if blob.exists():
        json_string = blob.download_as_text()
        try:
            metadata = json.loads(json_string)
            title = metadata.get("title", "Untitled")
            description = metadata.get("description", "No Description Available")
        except json.JSONDecodeError:
            title = "Untitled"
            description = "Could not parse description."
    else:
        title = "Untitled"
        description = "No Description Available"

    return render_template("image.html", filename=filename, title=title, description=description, image_url=image_url)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
