import os

from core import download_spotify


# ----------------------------- User prompts --------------------------------

def get_valid_directory():
    """Prompts the user for a download folder and ensures it exists."""
    while True:
        directory = input("\nEnter target directory to save MP3 (Leave blank for current folder): ").strip()

        if not directory:
            return "."  # Current directory

        # Clean up path and expand user home directory symbols like ~
        directory = os.path.abspath(os.path.expanduser(directory))

        try:
            if not os.path.exists(directory):
                os.makedirs(directory)
                print(f"📁 Created folder: {directory}")
            return directory
        except Exception as e:
            print(f"❌ Invalid directory or permission denied. Error: {e}. Please try again.")

def get_valid_bitrate():
    """Prompts the user for a bitrate and validates the input."""
    print("\nSelect your desired MP3 quality (bitrate):")
    print("1. 128 kbps (Standard quality / smaller file)")
    print("2. 192 kbps (High quality - Recommended)")
    print("3. 256 kbps (Very high quality)")
    print("4. 320 kbps (Highest quality / larger file)")
    print("5. Custom bitrate")

    while True:
        choice = input("Enter choice (1-5) or directly enter a value (e.g., 256): ").strip()

        if choice == '1':
            return '128'
        elif choice == '2':
            return '192'
        elif choice == '3':
            return '256'
        elif choice == '4':
            return '320'
        elif choice == '5':
            custom = input("Enter custom bitrate in kbps (e.g., 160): ").strip()
            if custom.isdigit():
                return custom
        elif choice.isdigit():
            return choice

        print("❌ Invalid input. Please enter a number between 1-5 or a valid numeric bitrate.")

def get_yes_no(prompt, default=True):
    """Simple yes/no prompt; Enter accepts the default."""
    hint = "Y/n" if default else "y/N"
    while True:
        answer = input(f"{prompt} [{hint}]: ").strip().lower()
        if not answer:
            return default
        if answer in ('y', 'yes'):
            return True
        if answer in ('n', 'no'):
            return False
        print("❌ Please answer y or n.")


if __name__ == "__main__":
    url = input("Enter Spotify Track, Album, or Playlist URL: ").strip()
    if url:
        output_folder = get_valid_directory()
        kbps = get_valid_bitrate()
        extra_metadata = get_yes_no(
            "\nFetch extra metadata (genre, BPM, label, ISRC, lyrics, MusicBrainz IDs, ...)? "
            "Slower, about 5-10 seconds per track")
        download_spotify(url, kbps, output_folder, enrich=extra_metadata)
    else:
        print("❌ URL cannot be empty.")
