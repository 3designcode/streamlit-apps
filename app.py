from dotenv import load_dotenv
import anthropic
import streamlit as st

load_dotenv()

def get_response(user_input):
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-3-5-sonnet-20240620",
        max_tokens=1024,
        system="You are an expert travel agent.",
        messages=[{"role": "user", "content": user_input}],
    )

    return response.content[0].text

st.title("AI Travel Agent: Itinerary Generator")
user_content = st.text_input("Enter your travel destination and planned days")

if st.button("Generate Itinerary"):
    if not user_content:
        st.warning("Please enter a destination and planned days")
    generated_itinerary = get_response(user_content)
    st.success("Itinerary Generated Successfully!")
    st.text_area("Generated Itinerary", generated_itinerary, height=300)

