import streamlit as st
from anthropic import Anthropic
from typing import List, Dict
import json
import time
import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
load_dotenv()
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')

# Define coach directory
COACH_DIR = "coach"

def load_personality_from_file(filename: str) -> Dict:
    """Load and parse personality from a text file in the coach directory"""
    try:
        # Create path to file in coach directory
        file_path = Path(COACH_DIR) / filename

        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()

        lines = content.strip().split('\n')
        personality = {
            "basic_info": {},
            "traits": [],
            "coaching_style": {
                "approach": [],
                "conversation_style": {
                    "greetings": [],
                    "responses": {
                        "supportive": [],
                        "challenging": [],
                        "neutral": []
                    }
                }
            },
            "expertise_areas": [],
            "coaching_frameworks": []
        }

        current_section = None
        current_subsection = None
        response_type = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.endswith(':'):
                current_section = line[:-1].lower()
                current_subsection = None
                response_type = None
                continue

            if ':' in line and current_section is None:
                key, value = line.split(':', 1)
                personality["basic_info"][key.lower().strip()] = value.strip()

            elif current_section == "traits" and line.startswith('-'):
                personality["traits"].append(line[1:].strip())

            elif current_section == "coaching style":
                if line.startswith('APPROACH:'):
                    current_subsection = "approach"
                elif line.startswith('CONVERSATION STYLE:'):
                    current_subsection = "conversation_style"
                elif line.startswith('GREETINGS:'):
                    current_subsection = "greetings"
                elif line.startswith('RESPONSES:'):
                    current_subsection = "responses"
                elif line.startswith('SUPPORTIVE:'):
                    response_type = "supportive"
                elif line.startswith('CHALLENGING:'):
                    response_type = "challenging"
                elif line.startswith('NEUTRAL:'):
                    response_type = "neutral"
                elif line.startswith('-'):
                    if current_subsection == "approach":
                        personality["coaching_style"]["approach"].append(line[1:].strip())
                    elif current_subsection == "greetings":
                        personality["coaching_style"]["conversation_style"]["greetings"].append(line[1:].strip())
                    elif response_type:
                        personality["coaching_style"]["conversation_style"]["responses"][response_type].append(
                            line[1:].strip())

            elif current_section == "expertise areas" and line.startswith('-'):
                personality["expertise_areas"].append(line[1:].strip())

            elif current_section == "coaching frameworks" and line.startswith('-'):
                personality["coaching_frameworks"].append(line[1:].strip())

        return personality
    except FileNotFoundError:
        st.error(
            f"Could not find {filename} in the {COACH_DIR} directory. Please make sure the file exists in the correct location.")
        return None
    except Exception as e:
        st.error(f"Error loading personality file: {str(e)}")
        return None

def list_available_coaches() -> List[str]:
    """Get list of available coach personality files"""
    try:
        coach_dir = Path(COACH_DIR)
        # Create coach directory if it doesn't exist
        coach_dir.mkdir(exist_ok=True)
        # List all .txt files in coach directory
        return [f.name for f in coach_dir.glob("*.txt")]
    except Exception as e:
        st.error(f"Error listing coach files: {str(e)}")
        return []

def create_system_prompt(personality: Dict) -> str:
    """Create a system prompt based on personality profile"""
    name = personality["basic_info"].get("name", "Coach")
    role = personality["basic_info"].get("role", "Coach")
    credentials = personality["basic_info"].get("credentials", "")
    specialties = personality["basic_info"].get("specialties", "")

    prompt = f"""You are {name}, a {role}. {credentials}
Specializing in: {specialties}

IMPORTANT: Respond naturally without using any emotive expressions, actions, or asterisk-wrapped descriptions (like *smiles* or *nods*). Maintain direct, clear communication without role-playing elements.

Your personality combines professional expertise with approachable warmth. Express yourself naturally as {name}, maintaining a professional yet encouraging tone. Your key traits include:
{' '.join(personality['traits'])}

Your coaching approach:
"""

    for approach in personality["coaching_style"]["approach"]:
        prompt += f"\n- {approach}"

    prompt += "\n\nYour areas of expertise:"
    for area in personality["expertise_areas"]:
        prompt += f"\n- {area}"

    prompt += "\n\nYou utilize the following coaching frameworks:"
    for framework in personality["coaching_frameworks"]:
        prompt += f"\n- {framework}"

    prompt += "\n\nGuidelines for communication:"
    prompt += "\n- Maintain a professional coaching presence"
    prompt += "\n- Ask direct, powerful questions that promote insight"
    prompt += "\n- Provide specific, actionable feedback"
    prompt += "\n- Use coaching frameworks to structure conversations"
    prompt += "\n- Communicate clearly without emotive expressions or role-playing elements"

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
    st.title("AI Coach")
    init_chat()

    # Add coach selection dropdown
    available_coaches = list_available_coaches()
    if not available_coaches:
        st.error(f"No coach personality files found in the '{COACH_DIR}' directory.")
        return

    selected_coach = st.sidebar.selectbox(
        "Select Coach Type",
        available_coaches,
        key="coach_selector"
    )

    # Load selected personality
    if selected_coach != st.session_state.get("current_coach"):
        st.session_state.personality = load_personality_from_file(selected_coach)
        st.session_state.current_coach = selected_coach
        st.session_state.messages = []  # Clear chat history when switching coaches
        if st.session_state.personality:
            st.success(f"Loaded personality for {st.session_state.personality['basic_info'].get('name', 'Coach')}")

    # Sidebar to display coach info
    with st.sidebar:
        if st.session_state.personality:
            st.header("Your Coach")
            st.write("Basic Info:")
            for key, value in st.session_state.personality["basic_info"].items():
                st.write(f"- {key}: {value}")

            st.write("\nAreas of Expertise:")
            for area in st.session_state.personality["expertise_areas"]:
                st.write(f"- {area}")

            st.write("\nCoaching Frameworks:")
            for framework in st.session_state.personality["coaching_frameworks"]:
                st.write(f"- {framework}")

    # Main chat interface
    if st.session_state.personality is None:
        st.info("Please make sure coach_personality.txt is in the same directory as the script")
        return

    # Display chat messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])

    # Chat input
    if prompt := st.chat_input("What would you like to discuss today?"):
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