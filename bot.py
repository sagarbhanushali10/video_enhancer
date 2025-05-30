import os
import subprocess
import logging
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

# Function to enhance video resolution with progress updates
def enhance_video(input_path, output_path, update: Update, is_callback_query=False):
    try:
        # FFmpeg command with enhancement filters
        command = [
            "ffmpeg",
            "-i", input_path,
            "-vf", "hqdn3d,unsharp",  # Apply denoising and sharpening filters
            "-c:v", "libx264",  # Use H.264 codec
            "-preset", "medium",  # Balanced encoding speed
            "-crf", "18",  # High-quality encoding (lower CRF = better quality)
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
        if is_callback_query:
            query = update.callback_query
            progress_message = query.message.reply_text("Enhancing video... 0% complete")
        else:
            progress_message = update.message.reply_text("Enhancing video... 0% complete")

        # Regex to parse FFmpeg progress
        time_regex = re.compile(r"time=(\d+:\d+:\d+\.\d+)")
        duration_regex = re.compile(r"Duration: (\d+:\d+:\d+\.\d+)")

        # Extract total video duration
        total_duration = None
        while True:
            line = process.stderr.readline() if process.stderr else ""
            if not line:
                break
            match = duration_regex.search(line)
            if match:
                time_str = match.group(1)
                hours, minutes, seconds = map(float, time_str.split(":"))
                total_duration = hours * 3600 + minutes * 60 + seconds
                break

        if not total_duration:
            raise ValueError("Could not determine video duration.")

        # Track the last updated progress percentage
        last_progress_percent = -1

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

                # Only update the message if the progress percentage has changed
                if progress_percent != last_progress_percent:
                    # Update progress message
                    if is_callback_query:
                        progress_message.edit_text(f"Enhancing video... {progress_percent}% complete")
                    else:
                        progress_message.edit_text(f"Enhancing video... {progress_percent}% complete")

                    # Update the last progress percentage
                    last_progress_percent = progress_percent

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
    input_path = None  # Initialize input_path to avoid UnboundLocalError
    try:
        # Download the video
        file = update.message.video.get_file()
        input_path = "input.mp4"
        file.download(input_path)

        # Get current resolution
        current_resolution = get_video_resolution(input_path)
        context.user_data['input_path'] = input_path
        context.user_data['current_resolution'] = current_resolution

        # Send enhancement options
        keyboard = [
            [InlineKeyboardButton("Enhance Quality", callback_data="enhance")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text(
            f"Current resolution: {current_resolution}\nClick 'Enhance Quality' to improve the video.",
            reply_markup=reply_markup
        )
    except ValueError as e:
        update.message.reply_text(f"Error: {str(e)}. Please try again with a valid video file.")
        logger.error(f"Error processing video: {str(e)}")
        if input_path and os.path.exists(input_path):  # Check if input_path exists before removing
            os.remove(input_path)
    except Exception as e:
        update.message.reply_text("An unexpected error occurred. Please try again later.")
        logger.error(f"Unexpected error: {str(e)}")
        if input_path and os.path.exists(input_path):  # Check if input_path exists before removing
            os.remove(input_path)

# Handle enhancement selection
def handle_resolution_selection(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    try:
        # Get selected option
        selected_option = query.data
        input_path = context.user_data['input_path']
        output_path = "output.mp4"

        if selected_option == "enhance":
            # Enhance video (pass query for callback handling)
            enhance_video(input_path, output_path, update, is_callback_query=True)

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

# Error handler
def error_handler(update: Update, context: CallbackContext):
    """Log the error and send a message to the user."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    if update and update.message:
        update.message.reply_text("An unexpected error occurred. Please try again later.")
    elif update and update.callback_query:
        update.callback_query.message.reply_text("An unexpected error occurred. Please try again later.")

# Main function
def main():
    try:
        # Access the bot token from the environment variable
        bot_token = os.getenv("BOT_TOKEN")
        if not bot_token:
            logger.error("BOT_TOKEN environment variable is not set.")
            raise ValueError("BOT_TOKEN environment variable is not set.")

        updater = Updater(bot_token, use_context=True)
        dispatcher = updater.dispatcher

        # Register handlers
        dispatcher.add_handler(CommandHandler("start", start))
        dispatcher.add_handler(MessageHandler(Filters.all, handle_message))
        dispatcher.add_handler(CallbackQueryHandler(handle_resolution_selection))

        # Register error handler
        dispatcher.add_error_handler(error_handler)

        # Clear any pending updates to avoid conflicts
        updater.bot.get_updates(offset=-1)

        # Start the bot
        logger.info("Starting the bot...")
        updater.start_polling()

        # Run the bot until you press Ctrl-C
        updater.idle()
    except Exception as e:
        logger.error(f"Critical error starting the bot: {str(e)}")

if __name__ == "__main__":
    main()
