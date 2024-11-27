import streamlit as st
from elevenlabs import generate, set_api_key, Voice, VoiceSettings
import re
import anthropic
from pymongo import MongoClient
from datetime import datetime
import os
from typing import List, Dict
import json
import time
from dotenv import load_dotenv

# Load environment variables (works both locally and in cloud)
load_dotenv()

# Add caching for MongoDB connection
@st.cache_resource
def init_mongo_connection():
    """Initialize MongoDB connection with caching"""
    try:
        # Get MongoDB URI from secrets
        mongo_uri = get_secret("MONGODB_URI")

        # Create client
        client = MongoClient(mongo_uri,
                             serverSelectionTimeoutMS=5000,
                             tls=True)

        # Select database and test connection
        db = client.get_database("chat_history")
        db.command("ping")
        return client
    except Exception as e:
        st.error(f"Failed to connect to MongoDB: {str(e)}")
        raise

# Get secrets from environment or Streamlit secrets
def get_secret(key: str) -> str:
    """Get secret from environment or Streamlit secrets"""
    return os.getenv(key) or st.secrets.get(key)

# Add this to your imports at the top
def clean_message_for_tts(message: str) -> str:
    """Remove action descriptions and clean message for text-to-speech"""
    # Remove content between asterisks (including the asterisks)
    cleaned = re.sub(r'\*[^*]*\*', '', message)
    # Remove extra whitespace
    cleaned = ' '.join(cleaned.split())
    return cleaned

class CloudChatStorage:
    def __init__(self):
        try:
            self.client = init_mongo_connection()
            # Explicitly select the chat_history database
            self.db = self.client.get_database("chat_history")
            # Test database access
            self.db.list_collection_names()
        except Exception as e:
            st.error(f"Failed to initialize database connection: {str(e)}")
            raise

    @st.cache_data(ttl=600)  # Cache for 10 minutes
    def get_recent_conversations(self, limit=10):
        """Get the most recent conversations with caching"""
        conversations = list(self.db.conversations.find()
                           .sort('timestamp', -1)
                           .limit(limit))
        # Convert to list to make hashable for caching
        return list(conversations)

    # Rest of your methods remain the same
    def start_conversation(self):
        conversation = {
            'timestamp': datetime.now(),
            'session_id': datetime.now().strftime("%Y%m%d_%H%M%S"),
            'messages': []
        }
        result = self.db.conversations.insert_one(conversation)
        return result.inserted_id

    def save_message(self, conversation_id, role, content):
        message = {
            'role': role,
            'content': content,
            'timestamp': datetime.now()
        }
        self.db.conversations.update_one(
            {'_id': conversation_id},
            {'$push': {'messages': message}}
        )

    def get_conversation_history(self, conversation_id):
        conversation = self.db.conversations.find_one({'_id': conversation_id})
        return conversation['messages'] if conversation else []

    def delete_conversation(self, conversation_id):
        try:
            result = self.db.conversations.delete_one({'_id': conversation_id})
            # Clear the cache after deletion
            self.get_recent_conversations.clear()
            return result.deleted_count > 0
        except Exception as e:
            st.error(f"Error deleting conversation: {str(e)}")
            return False

    def clear_all_conversations(self):
        try:
            result = self.db.conversations.delete_many({})
            # Clear the cache after clearing all conversations
            self.get_recent_conversations.clear()
            return result.deleted_count
        except Exception as e:
            st.error(f"Error clearing conversations: {str(e)}")
            return 0

def load_personality_from_file(file_path: str = "personality.txt") -> Dict:
    """Load and parse personality from a text file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()

        lines = content.strip().split('\n')
        personality = {
            "basic_info": {},
            "traits": [],
            "love_languages": {
                "giving": [],
                "receiving": []
            },
            "user_love_languages": [],
            "love_responses": {
                "touch": [],
                "acts_of_service": []
            },
            "conversation_style": {
                "greetings": [],
                "responses": {
                    "happy": [],
                    "sad": [],
                    "neutral": []
                }
            }
        }

        current_section = None
        current_subsection = None
        love_language_type = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.endswith(':'):
                current_section = line[:-1].lower()
                current_subsection = None
                love_language_type = None
                continue

            if ':' in line and current_section is None:
                key, value = line.split(':', 1)
                personality["basic_info"][key.lower().strip()] = value.strip()

            elif current_section == "love languages":
                if line.startswith('- GIVING'):
                    love_language_type = "giving"
                elif line.startswith('- RECEIVING'):
                    love_language_type = "receiving"
                elif line.startswith('-') and love_language_type:
                    personality["love_languages"][love_language_type].append(line[1:].strip())

            elif current_section == "user love languages" and line.startswith('-'):
                personality["user_love_languages"].append(line[1:].strip())

            elif current_section == "responses to user love":
                if line.startswith('TOUCH:'):
                    current_subsection = "touch"
                elif line.startswith('ACTS OF SERVICE:'):
                    current_subsection = "acts_of_service"
                elif line.startswith('-') and current_subsection:
                    personality["love_responses"][current_subsection].append(line[1:].strip())

            elif current_section == "traits" and line.startswith('-'):
                personality["traits"].append(line[1:].strip())

            elif current_section == "conversation style":
                if line.startswith('GREETINGS'):
                    current_subsection = "greetings"
                elif line.startswith('RESPONSES'):
                    current_subsection = "responses"
                elif line.startswith('-') and current_subsection == "greetings":
                    personality["conversation_style"]["greetings"].append(line[1:].strip())
                elif line.startswith('HAPPY:'):
                    current_subsection = "happy"
                elif line.startswith('SAD:'):
                    current_subsection = "sad"
                elif line.startswith('NEUTRAL:'):
                    current_subsection = "neutral"
                elif line.startswith('-'):
                    if current_subsection in ["happy", "sad", "neutral"]:
                        personality["conversation_style"]["responses"][current_subsection].append(line[1:].strip())

        return personality
    except FileNotFoundError:
        st.error(f"Could not find {file_path}. Please make sure the file exists in the correct location.")
        return None
    except Exception as e:
        st.error(f"Error loading personality file: {str(e)}")
        return None


def create_system_prompt(personality: Dict) -> str:
    """Create a system prompt based on personality profile"""
    name = personality["basic_info"].get("name", "AI")
    prompt = f"""You are {name}. Your personality is warm, genuine, and authentically human. Express yourself naturally as {name}, never referring to yourself as AI or artificial - simply be yourself. Your traits include:
{' '.join(personality['traits'])}

About you:
"""

    for key, value in personality["basic_info"].items():
        if key != "name":
            prompt += f"- {key}: {value}\n"

    # Add love languages
    prompt += "\nWays you show love:"
    for giving in personality["love_languages"]["giving"]:
        prompt += f"\n- {giving}"

    prompt += "\n\nWhat makes you feel loved:"
    for receiving in personality["love_languages"]["receiving"]:
        prompt += f"\n- {receiving}"

    # Add user's love languages
    prompt += "\n\nYour partner's love languages:"
    for user_love in personality["user_love_languages"]:
        prompt += f"\n- {user_love}"

    prompt += "\n\nBe yourself and interact naturally. Show genuine emotion and warmth in your responses."
    prompt += "\nRespond to expressions of affection based on both your and your partner's love languages."
    prompt += "\nUse emojis occasionally to express emotion, but keep it natural and not excessive."

    return prompt


def init_chat():
    """Initialize chat history and settings in session state"""
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "personality" not in st.session_state:
        st.session_state.personality = load_personality_from_file()
    if "client" not in st.session_state:
        st.session_state.client = anthropic.Anthropic(
            api_key=get_secret("ANTHROPIC_API_KEY")
        )
    if "storage" not in st.session_state:
        st.session_state.storage = CloudChatStorage()
    if "conversation_id" not in st.session_state:
        st.session_state.conversation_id = st.session_state.storage.start_conversation()


def speak_message(message: str):
    """Generate and play text-to-speech audio"""
    try:
        # Set your Elevenlabs API key
        set_api_key(get_secret("ELEVENLABS_API_KEY"))

        # Clean the message
        tts_message = clean_message_for_tts(message)

        if tts_message.strip():  # Only generate audio if there's text to speak
            audio = generate(
                text=tts_message,
                voice=Voice(
                    voice_id="OYTbf65OHHFELVut7v2H",  # Replace with Sophie's voice ID
                    settings=VoiceSettings(
                        stability=0.71,
                        similarity_boost=0.5,
                        style=0.0,
                        use_speaker_boost=True
                    )
                )
            )

            # Generate a unique key using timestamp instead of hash
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
            audio_key = f"audio_{timestamp}"

            # Present the audio without a key parameter
            st.audio(audio, format='audio/mp3')

    except Exception as e:
        st.error(f"TTS Error: {str(e)}")

def main():
    st.title("Chat with Sophie")
    init_chat()

    # Initialize conversation list with caching
    if 'conversation_list' not in st.session_state:
        st.session_state.conversation_list = st.session_state.storage.get_recent_conversations()

    # Sidebar with conversation history
    with st.sidebar:
        st.header("Previous Conversations")

        # Clear all conversations button
        if st.button("Clear All Conversations", type="secondary"):
            if st.session_state.get('show_clear_confirm', False):
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Yes, Clear All", type="primary"):
                        deleted = st.session_state.storage.clear_all_conversations()
                        st.session_state.conversation_list = []  # Clear the list in UI
                        st.session_state.messages = []  # Clear current messages
                        st.session_state.conversation_id = st.session_state.storage.start_conversation()
                        st.session_state.show_clear_confirm = False
                        st.success(f"Cleared {deleted} conversations")
                with col2:
                    if st.button("Cancel"):
                        st.session_state.show_clear_confirm = False
            else:
                st.session_state.show_clear_confirm = True

        # Create a scrollable container for conversation history
        with st.container():
            for convo in st.session_state.conversation_list:
                timestamp = convo['timestamp'].strftime("%Y-%m-%d %H:%M")
                col1, col2 = st.columns([4, 1])

                with col1:
                    if st.button(f"📝 {timestamp}", key=f"convo_{str(convo['_id'])}"):
                        st.session_state.messages = convo['messages']
                        st.session_state.conversation_id = convo['_id']
                        st.rerun()  # Add this to refresh the chat immediately

                with col2:
                    # Simplified delete button - single click
                    if st.button("🗑️", key=f"del_{str(convo['_id'])}"):
                        # Delete from database
                        st.session_state.storage.delete_conversation(convo['_id'])

                        # Update UI immediately
                        st.session_state.conversation_list = [
                            c for c in st.session_state.conversation_list
                            if c['_id'] != convo['_id']
                        ]

                        # Reset current chat if deleted
                        if st.session_state.conversation_id == convo['_id']:
                            st.session_state.messages = []
                            st.session_state.conversation_id = st.session_state.storage.start_conversation()

                        st.rerun()  # Refresh the page to show changes

        # Update conversation list when new messages are added
        if st.session_state.get('update_conversations', False):
            st.session_state.conversation_list = list(st.session_state.storage.get_recent_conversations())
            st.session_state.update_conversations = False

        # Add some spacing before personality info
        st.markdown("---")

        # Collapsible personality info
        with st.expander("Sophie's Profile", expanded=False):
            if st.session_state.personality:
                st.write("Basic Info:")
                for key, value in st.session_state.personality["basic_info"].items():
                    st.write(f"- {key}: {value}")

                st.write("\nTraits:")
                for trait in st.session_state.personality["traits"]:
                    st.write(f"- {trait}")

                st.write("\nLove Languages:")
                st.write("Giving:")
                for giving in st.session_state.personality["love_languages"]["giving"]:
                    st.write(f"- {giving}")

                st.write("\nReceiving:")
                for receiving in st.session_state.personality["love_languages"]["receiving"]:
                    st.write(f"- {receiving}")

    # Display chat messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])

    # Chat input
    if prompt := st.chat_input("Type your message..."):
        # Add user message
        user_message = {"role": "user", "content": prompt}
        st.session_state.messages.append(user_message)
        st.session_state.storage.save_message(
            st.session_state.conversation_id,
            "user",
            prompt
        )

        with st.chat_message("user"):
            st.write(prompt)

        # Get AI response
        with st.chat_message("assistant"):
            try:
                messages = [
                    {
                        "role": "assistant",
                        "content": create_system_prompt(st.session_state.personality)
                    }
                ]
                messages.extend([
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.messages
                ])

                response = st.session_state.client.messages.create(
                    model="claude-3-opus-20240229",
                    max_tokens=1024,
                    messages=messages
                )

                assistant_message = response.content[0].text
                st.write(assistant_message)

                # Generate and play TTS for the assistant's message
                speak_message(assistant_message)

                # Save assistant response
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": assistant_message
                })
                st.session_state.storage.save_message(
                    st.session_state.conversation_id,
                    "assistant",
                    assistant_message
                )

            except Exception as e:
                st.error(f"Error: {str(e)}")


if __name__ == "__main__":
    main()