import streamlit as st
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

# Get secrets from environment or Streamlit secrets
def get_secret(key: str) -> str:
    """Get secret from environment or Streamlit secrets"""
    return os.getenv(key) or st.secrets.get(key)

class CloudChatStorage:
    def __init__(self):
        mongo_uri = get_secret("MONGODB_URI")
        self.client = MongoClient(mongo_uri)
        self.db = self.client.chat_history
        
    def start_conversation(self):
        """Start a new conversation and return its ID"""
        conversation = {
            'timestamp': datetime.now(),
            'session_id': datetime.now().strftime("%Y%m%d_%H%M%S"),
            'messages': []
        }
        result = self.db.conversations.insert_one(conversation)
        return result.inserted_id
    
    def save_message(self, conversation_id, role, content):
        """Save a message to the conversation"""
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
        """Retrieve all messages from a specific conversation"""
        conversation = self.db.conversations.find_one({'_id': conversation_id})
        return conversation['messages'] if conversation else []
    
    def get_recent_conversations(self, limit=10):
        """Get the most recent conversations"""
        return list(self.db.conversations.find()
                   .sort('timestamp', -1)
                   .limit(limit))
    
    def delete_conversation(self, conversation_id):
        """Delete a specific conversation"""
        try:
            result = self.db.conversations.delete_one({'_id': conversation_id})
            return result.deleted_count > 0
        except Exception as e:
            st.error(f"Error deleting conversation: {str(e)}")
            return False

    def clear_all_conversations(self):
        """Delete all conversations"""
        try:
            result = self.db.conversations.delete_many({})
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
                if line.startswith('GIVING:'):
                    love_language_type = "giving"
                elif line.startswith('RECEIVING:'):
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

def main():
    st.title("Chat with Sophie")
    init_chat()

    # Initialize conversation list in session state if not present
    if 'conversation_list' not in st.session_state:
        st.session_state.conversation_list = list(st.session_state.storage.get_recent_conversations())
    
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