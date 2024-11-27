import streamlit as st
from anthropic import Anthropic
from typing import List, Dict
import json
import time
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')

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

def init_chat() -> None:
    """Initialize chat history and settings in session state"""
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "personality" not in st.session_state:
        st.session_state.personality = None
    if "client" not in st.session_state:
        st.session_state.client = Anthropic(api_key=ANTHROPIC_API_KEY)

def main():
    st.title("AI Girlfriend")
    init_chat()
    
    # Load personality from file
    if st.session_state.personality is None:
        st.session_state.personality = load_personality_from_file()
        if st.session_state.personality:
            st.success(f"Loaded personality for {st.session_state.personality['basic_info'].get('name', 'AI')}")
    
    # Sidebar to display personality info
    with st.sidebar:
        if st.session_state.personality:
            st.header("Current Personality")
            st.write("Basic Info:")
            for key, value in st.session_state.personality["basic_info"].items():
                st.write(f"- {key}: {value}")
            
            st.write("\nTraits:")
            for trait in st.session_state.personality["traits"]:
                st.write(f"- {trait}")

            st.write("\nLove Languages:")
            st.write("- Giving")
            for giving in st.session_state.personality["love_languages"]["giving"]:
                st.write(f"- {giving}")
                
            st.write("- Receiving")
            for receiving in st.session_state.personality["love_languages"]["receiving"]:
                st.write(f"- {receiving}")
    
    # Main chat interface
    if st.session_state.personality is None:
        st.info("Please make sure personality.txt is in the same directory as the script")
        return
    
    # Display chat messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])
    
    # Chat input
    if prompt := st.chat_input("Type your message..."):
        # Add user message to chat history
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)
            
        # Get AI response
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            full_response = ""
            
            try:
                messages = [
                    {
                        "role": "assistant",
                        "content": create_system_prompt(st.session_state.personality)
                    }
                ]
                messages.extend(st.session_state.messages)
                
                response = st.session_state.client.messages.create(
                    model="claude-3-opus-20240229",
                    max_tokens=1024,
                    messages=messages
                )
                
                full_response = response.content[0].text
                message_placeholder.markdown(full_response)
                
                # Add assistant response to chat history
                st.session_state.messages.append({"role": "assistant", "content": full_response})
                
            except Exception as e:
                st.error(f"Error: {str(e)}")
                return

if __name__ == "__main__":
    main()