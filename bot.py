import os
import subprocess
import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler
from dotenv import load_dotenv

# Load environment variables from .env file (optional for local development)
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Function to detect video resolution
def get_video_resolution(video_path):
    try:
        command = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=s=x:p=0",
            video_path
        ]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        resolution = result.stdout.strip()
        if not resolution:
            raise ValueError("Invalid video format or resolution could not be detected.")
        return resolution
    except Exception as e:
        logger.error(f"Error detecting resolution: {str(e)}")
        raise ValueError(f"Error detecting resolution: {str(e)}")

# Function to get video duration
def get_video_duration(video_path):
    try:
        command = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        duration = float(result.stdout.strip())
        return duration
    except Exception as e:
        logger.error(f"Error getting video duration: {str(e)}")
        raise ValueError(f"Error getting video duration: {str(e)}")

# Function to enhance video resolution with progress updates
def enhance_video(input_path, output_path, resolution, update: Update):
    try:
        width, height = resolution.split("x")
        scale_width = int(width)
        scale_height = int(height)

        # Get total video duration
        total_duration = get_video_duration(input_path)

        # FFmpeg command
        command = [
            "ffmpeg",
            "-i", input_path,
            "-vf", f"scale={scale_width}:{scale_height}",  # Resize to target resolution
            "-c:v", "libx264",  # Use H.264 codec
            "-preset", "ultrafast",  # Faster encoding
            "-b:v", "1M",  # Set a maximum bitrate (e.g., 1 Mbps)
            output_path
        ]

        # Start FFmpeg process
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

        # Send initial progress message
        progress_message = update.message.reply_text("Processing video... 0% complete")

        # Regex to parse FFmpeg progress
        time_regex = re.compile(r"time=(\d+:\d+:\d+\.\d+)")

        while True:
            line = process.stdout.readline()
            if not line:
                break

            # Parse progress from FFmpeg output
            match = time_regex.search(line)
            if match:
                time_str = match.group(1)
                hours, minutes, seconds = map(float, time_str.split(":"))
                current_seconds = hours * 3600 + minutes * 60 + seconds

                # Calculate progress percentage
                progress_percent = min(int((current_seconds / total_duration) * 100), 100)

                # Update progress message
                progress_message.edit_text(f"Processing video... {progress_percent}% complete")

        # Wait for FFmpeg to finish
        process.wait()

        if process.returncode != 0:
            raise RuntimeError("FFmpeg processing failed.")

        logger.info("FFmpeg processing completed successfully.")
    except Exception as e:
        logger.error(f"Error enhancing video: {str(e)}")
        raise RuntimeError(f"Error enhancing video: {str(e)}")

# Start command handler
def start(update: Update, context: CallbackContext):
    update.message.reply_text("Welcome! Send me a video to enhance its quality.")

# Handle video upload
def handle_message(update: Update, context: CallbackContext):
    try:
        # Check if the message contains a video
        if update.message.video:
            handle_video(update, context)
        else:
            update.message.reply_text("Please send a video file only. Other file types are not supported.")
    except Exception as e:
        logger.error(f"Error handling message: {str(e)}")
        update.message.reply_text("An unexpected error occurred. Please try again later.")

# Handle video processing
def handle_video(update: Update, context: CallbackContext):
    try:
        # Download the video
        file = update.message.video.get_file()
        input_path = "input.mp4"
        file.download(input_path)

        # Get current resolution
        current_resolution = get_video_resolution(input_path)
        context.user_data['input_path'] = input_path
        context.user_data['current_resolution'] = current_resolution

        # Send resolution options
        keyboard = [
            [InlineKeyboardButton("720p", callback_data="720"),
             InlineKeyboardButton("1080p", callback_data="1080")],
            [InlineKeyboardButton("2K", callback_data="1440")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text(
            f"Current resolution: {current_resolution}\nSelect the desired resolution:",
            reply_markup=reply_markup
        )
    except ValueError as e:
        update.message.reply_text(f"Error: {str(e)}. Please try again with a valid video file.")
        logger.error(f"Error processing video: {str(e)}")
        if os.path.exists("input.mp4"):
            os.remove("input.mp4")
    except Exception as e:
        update.message.reply_text("An unexpected error occurred. Please try again later.")
        logger.error(f"Unexpected error: {str(e)}")
        if os.path.exists("input.mp4"):
            os.remove("input.mp4")

# Handle resolution selection
def handle_resolution_selection(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    try:
        # Get selected resolution
        selected_resolution = query.data
        input_path = context.user_data['input_path']
        output_path = "output.mp4"

        # Map resolution to width x height
        resolution_map = {
            "720": "1280x720",
            "1080": "1920x1080",
            "1440": "2560x1440"
        }
        target_resolution = resolution_map[selected_resolution]

        # Enhance video
        enhance_video(input_path, output_path, target_resolution, update)

        # Send enhanced video
        with open(output_path, "rb") as video_file:
            query.message.reply_video(video=video_file)

        # Clean up files
        os.remove(input_path)
        os.remove(output_path)
    except Exception as e:
        query.message.reply_text(f"Error processing video: {str(e)}. Please try again.")
        logger.error(f"Error processing resolution selection: {str(e)}")
        if os.path.exists(input_path):
            os.remove(input_path)
        if os.path.exists(output_path):
            os.remove(output_path)

# Main function
def main():
    try:
        # Access the bot token from the environment variable
        bot_token = os.getenv("BOT_TOKEN")
        if not bot_token:
            logger.error("BOT_TOKEN environment variable is not set.")
            raise ValueError("BOT_TOKEN environment variable is not set.")

        updater = Updater(bot_token)
        dispatcher = updater.dispatcher

        # Register handlers
        dispatcher.add_handler(CommandHandler("start", start))
        dispatcher.add_handler(MessageHandler(Filters.all, handle_message))
        dispatcher.add_handler(CallbackQueryHandler(handle_resolution_selection))

        # Start the bot
        logger.info("Starting the bot...")
        updater.start_polling()
        updater.idle()
    except Exception as e:
        logger.error(f"Critical error starting the bot: {str(e)}")

if __name__ == "__main__":
    main()
