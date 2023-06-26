from dotenv import load_dotenv
import streamlit as st
from audio_recorder_streamlit import audio_recorder
import time
import os
import torch
# import pyaudio
import whisper 
import wave
from stqdm import stqdm
from io import BytesIO
import io
import tempfile
import threading


# Load env variables from .env file
load_dotenv()
# Setup Model Storage
models_path = os.environ.get("MODELS_PATH")
# enable write permission on models_path
os.chmod(models_path, 0o775)

# AUDIO CONSTANTS
# FORMAT = pyaudio.paInt16
# CHANNELS = 1
# RATE = 16000
# FRAMES_PER_BUFFER = 3200
# DURATION = 11

# Init vars
model_file = ''
whisper_file = ''
audio_file = None


def main():
    global audio_file
    
    # Initialize Session State
    if 'stop_rec' not in st.session_state:
        st.session_state.stop_rec = False
        
    if 'audio_file' not in st.session_state:
        st.session_state.audio_file = None
        
    if 'whisper_loaded' not in st.session_state:
        st.session_state.whisper_loaded = False
        
    if 'model' not in st.session_state:
        st.session_state.model = None
        
    if 'transcribe_flag' not in st.session_state:
        st.session_state.transcribe_flag = False
        
    # Change Session State
    def stop_rec():
        # On button clicked
        st.session_state.stop_rec = True

    # DEBUG Session State
    # print("⚠️ Session State:", st.session_state)
    
    
    # Check if CUDA is available
    torch.cuda.is_available()
    DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    
    # Setup Audio Stream
    # p, stream = create_pyaudio_stream(FORMAT, CHANNELS, RATE, FRAMES_PER_BUFFER)    
    
    # Streamlit UI: Title
    st.title("🗣 ⇢ TalkSee ⇢ 👀")
    # UI Columns
    col1, col2 = st.columns(2)
    
    # Select WhisperAI model
    model = None
    with col1:
        st.header("Select Model")
        whisper_select = st.selectbox(
            'Available Multilingual Models',
            ('tiny', 'base', 'small', 'medium', 'large', 'large-v2'),
            help="""
                |  Size  | Parameters | Multilingual model | Required VRAM | Relative speed |
                |:------:|:----------:|:------------------:|:-------------:|:--------------:|
                |  tiny  |    39 M    |       `tiny`       |     ~1 GB     |      ~32x      |
                |  base  |    74 M    |       `base`       |     ~1 GB     |      ~16x      |
                | small  |   244 M    |      `small`       |     ~2 GB     |      ~6x       |
                | medium |   769 M    |      `medium`      |     ~5 GB     |      ~2x       |
                | large  |   1550 M   |      `large`       |    ~10 GB     |       1x       |
            """,
            label_visibility='collapsed'
        )
    ## Get models path
    whisper_file = os.path.join(models_path, f"{whisper_select}.pt")
    whisper_selected = None
    
    # Get model (if not already loaded)
    if st.session_state.model is None:
        st.session_state.model, whisper_selected = model_exists(whisper_select, DEVICE, models_path, col1, col2)
        
    with col1:
        st.text(f"✅ Torch Status: {DEVICE}")
        alert = st.text(f"✅ Model Loaded: {whisper_selected}")
    
    # Get user input
    ## Select Input Mode
    with col2:
        st.header("Select Input Mode")
        input_type = st.radio(
            'Select Input Mode',
            ('Mic', 'File'),
            label_visibility='collapsed',
            horizontal=True
        )     
        st.empty()     
            
    with col2:
        ## MIC or FILE
        if input_type == 'Mic':
            #  Render UI
            st.header("🎙️ Record Audio")
            #  Setup User Mic Input
            audio_data = setup_mic(col1, col2)   
            
            # DEBUG
            # print("🎙️ setup_mic: ", audio_data)
            # print("🎙️ type: ", type(audio_data))
            
        else:
            #  Render UI
            st.header("📂 Upload Audio")
            #  Setup User File Input
            audio_data = setup_file(col1, col2)
            
            # DEBUG
            # print("📂 setup_file:", audio_data)
            # print("📂 type:", type(audio_data))


    # Transcribe audio file
    if audio_data is not None and st.session_state.transcribe_flag:
        transcription = transcribe(audio_data, st.session_state.model, col1, col2)
        st.session_state.transcribe_flag = False  # Reset the flag

    # Session State DEBUGGER
    with st.expander("Session State"):
        st.session_state
    
    # main() end # 
    ##############


def model_exists(whisper_selected, device, models_path, col1, col2):
    if not whisper_selected:
        st.warning(f"Select a model! ⏫", icon="🚨")     
    
    else:
        ## Check if select model exists in models directory
        if not os.path.exists(whisper_file):

            with col1:
                download_info = st.info(f"Downloading Whisper {whisper_selected} model...")
                
                if whisper_selected:
                    # Create a separate thread for downloading the model
                    download_thread = threading.Thread(
                        target=download_model, 
                        args=(whisper_selected, device, models_path)
                    )
                    download_thread.start()
                    
                    # Use stqdm progress bar to show progress while the model is downloading
                    with stqdm(total=100, desc="Downloading", bar_format="{l_bar}{bar} [ETA: {remaining}]", ncols=100) as progress_bar:
                        for percent in range(100):
                            if not download_thread.is_alive():
                                # If thread is running
                                progress_bar.update(100 - progress_bar.n)  
                                # Complete the progress bar if the model is downloaded
                                break
                            progress_bar.update(1)
                            time.sleep(0.1)

                    # Wait for the download thread to finish and get the model
                    download_thread.join()
                    model = download_model(whisper_selected, device, models_path)
                        
                    # show loaded model if selected
                    if model:
                        # Update Session State
                        st.session_state.whisper_loaded = True
                
                # Render UI
                download_info.empty()
                
        else:
            # If model exists setup model object
            model = download_model(whisper_selected, device, models_path)
            print("Model Already DLd: ", model)
    
    return model, whisper_selected


def download_model(whisper_selected, device, models_path):
    model = whisper.load_model(
        whisper_selected,
        device=device,
        download_root=models_path
    )
    return model


# Handle User Input 
def setup_mic(col1, col2):
    global audio_file
    audio_data = None
        
    #  Streamlit Audio Recorder
    audio_bytes = audio_recorder(
        text='Record Audio',
        # icon_name="mic",
        pause_threshold=2.0, 
        sample_rate=41_000
    )
    
    # if button clicked
    if audio_bytes:  
        frames = []

        # Render UI
        print("Recording...")
        # rec_feedback = st.info("Recording...", icon="🔴")
        # start_time = time.time()
        
        # Initialize the progress bar placeholder
        progress_placeholder = st.empty()
        progress_bar = progress_placeholder.progress(0)
        
        # Initialize the counter variable
        # i = 0
        
        # Record Audio input
        # for i in range(int(rate / frames_per_buffer * duration)):
        # while True:
        #     data = stream.read(frames_per_buffer, exception_on_overflow=False)
        #     frames.append(data)  
            
        #     # Update the duration
        #     duration = range(int(rate / frames_per_buffer * (time.time() - start_time)))
            
            # Update the progress bar
            # progress = min((i + 1) / (rate / frames_per_buffer * len(duration)), 1.0)

            # progress_bar.progress(progress)
            
            # Increment the counter variable
            # i += 1  # Add this line
            
            # Check if the stop button is clicked and update st.session_state.stop_rec
            # if stop_button:
            #     st.session_state.stop_rec = True
                # print(st.session_state.stop_rec)
            
            # if getattr(st.session_state, 'stop_rec', False):
            #     print("Recording Stopped")
            #     break
    
        # Clear the progress bar when it's full
        progress_placeholder.empty()
            
        # Reset stop_rec for future recordings
        # st.session_state.stop_rec = False
        # st.session_state.rec_btn = False
            
        # Check if recording is done
        # if not st.session_state.stop_rec:
        #     print("Recording Finished!")
        # else:
        #     print("Recording Stopped")
            
            
        # Render UI
        # rec_feedback.empty()
        # progress.empty()
        
        

        # Save Recorded Audio to file
        # output_file_path = "output.wav"
        # with wave.open(output_file_path, "wb") as file:
        #     file.setnchannels(channels)
        #     file.setsampwidth(p.get_sample_size(format))
        #     file.setframerate(rate)
        #     # combine all elements in frames list into a binary string
        #     frames_bytes = b"".join(frames)
        #     file.writeframes(frames_bytes)
        
        # Read the binary content of the file
        with open('output.wav', 'rb') as f:
            file_content = f.read()
            
        # Open file from streamlit recorder
        with open("output.wav", "wb") as f:
            f.write(audio_bytes)
        # st.audio(audio_bytes, format="audio/wav")

        # # Create a BytesIO object // Set name and type
        uploaded_file = BytesIO(audio_bytes)
        uploaded_file.name = 'output.wav'
        uploaded_file.type = 'audio/wav'
        uploaded_file.id = len(uploaded_file.getvalue()) if st.session_state.audio_file is not None else 0
        uploaded_file.size = len(audio_bytes)

        # # Convert BytesIO object to a file-like object
        file_like_object = io.BytesIO(uploaded_file.getvalue())

        # # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
            temp_file.write(uploaded_file.getvalue())
            temp_file.flush()

        #     # Load Recorded file to memory
            audio_data = whisper.load_audio(temp_file.name)
            audio_data = whisper.pad_or_trim(audio_data) 

        # # Clean up temporary file
        os.unlink(temp_file.name)
        
        # # Update Session_State
        st.session_state.audio_file = uploaded_file
        st.session_state.transcribe_flag = True
        
        if audio_data.size > 0:
            # Render Playback Audio File
            st.header("🎧 Recorded File")
            st.audio(uploaded_file)
        
    # Close the stream and terminate the PyAudio object
    # stream.stop_stream()
    # stream.close()
    # p.terminate()

    return st.session_state.audio_file if st.session_state.audio_file else None
    
    
def setup_file(col1, col2):
    global audio_file
    
    with col2:
        ## Upload Pre-Recorded Audio file
        audio_file = st.file_uploader(
            "Upload Audio File", 
            key="audio_file",
            # Supported file types
            type=["wav", "mp3", "m4a"],
            label_visibility='collapsed'
        )
        
        # Update Session_State
        st.session_state.transcribe_flag = True
        
        if audio_file:
            # Render Playback Audio File
            st.header("🎧 Uploaded File")
            st.audio(audio_file)
                
    return audio_file


# Transcribe Audio
def transcribe(audio_file, model, col1, col2):
    transcription = {}
    
    # if st.button("Transcribe!"):
    if audio_file is not None:
        #  Render UI
        feedback = st.info("Transcribing...")
        # audio_file.name == filePath
        transcription = model.transcribe(audio_file.name)

        # Render UI
        st.header("✍️ Transcription")
        st.markdown(transcription["text"])
        feedback.empty()
        with col1:
            st.success(
                    "Transcription Complete!",
                    icon="🤩"
                )
    else:
        st.error("Please input a valid audio file!")

    return transcription
    

# Run
if __name__ == "__main__":
    main()