import os
import datetime
import streamlit as st # वेब इंटरफ़ेस बनाने के लिए
import openai # ChatGPT के लिए
import requests # OpenWeatherMap API से डेटा प्राप्त करने के लिए
import sqlite3 # तुम्हारे कस्टम ज्ञान को स्टोर करने के लिए
import json # JSON डेटा को प्रोसेस करने के लिए

# API कुंजियां Streamlit Secrets से प्राप्त की जाएंगी
try:
    OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
    OPENWEATHER_API_KEY = st.secrets["OPENWEATHER_API_KEY"]
except KeyError as e:
    # Streamlit इंटरफ़ेस के लिए त्रुटि दिखाएं
    st.error(f"त्रुटि: API कुंजी '{e}' नहीं मिली। कृपया सुनिश्चित करें कि आपने इसे Streamlit Secrets में जोड़ा है।")
    st.stop() # अगर कुंजी नहीं मिली तो ऐप को रोक दें


# OpenAI क्लाइंट को इनिशियलाइज़ करें
openai.api_key = OPENAI_API_KEY

# डेटाबेस सेटअप और ज्ञान फ़ंक्शंस
# ध्यान दें: Streamlit Cloud में /tmp फोल्डर अस्थायी होता है।
# अगर तुम चाहते हो कि तुम्हारा ज्ञान स्थायी रहे, तो तुम्हें Google Firestore
# या किसी अन्य क्लाउड डेटाबेस का उपयोग करना होगा। अभी के लिए, यह हर रीस्टार्ट पर रीसेट हो जाएगा।
DATABASE_FILE = "/tmp/my_chatbot_knowledge.db" 

def setup_database():
    """डेटाबेस और टेबल को बनाता है यदि वे मौजूद नहीं हैं।"""
    conn = sqlite3.connect(DATABASE_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS knowledge (
            id INTEGER PRIMARY KEY,
            question TEXT UNIQUE,
            answer TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_knowledge_to_db(question, answer):
    """डेटाबेस में नया ज्ञान जोड़ता है।"""
    conn = sqlite3.connect(DATABASE_FILE)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO knowledge (question, answer) VALUES (?, ?)", (question, answer))
        conn.commit()
        return "ज्ञान सफलतापूर्वक जोड़ा गया।"
    except sqlite3.IntegrityError:
        return "इस प्रश्न के लिए ज्ञान पहले से मौजूद है।"
    except Exception as e:
        return f"ज्ञान जोड़ने में त्रुटि हुई: {e}"
    finally:
        conn.close()

def get_knowledge_from_db(question):
    """डेटाबेस से प्रश्न का उत्तर प्राप्त करता है।"""
    conn = sqlite3.connect(DATABASE_FILE)
    c = conn.cursor()
    c.execute("SELECT answer FROM knowledge WHERE question = ?", (question,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

# OpenWeatherMap फ़ंक्शन (मौसम के लिए)
def get_weather(city):
    """किसी शहर के लिए वर्तमान मौसम की जानकारी प्राप्त करता है।"""
    base_url = "http://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": city,
        "appid": OPENWEATHER_API_KEY,
        "units": "metric" # सेल्सियस में तापमान के लिए
    }
    try:
        response = requests.get(base_url, params=params)
        response.raise_for_status() # HTTP त्रुटियों (जैसे 404) के लिए अपवाद उठाएं
        data = response.json()

        if data.get("cod") == 200: # यदि API कॉल सफल रहा
            main_weather = data["weather"][0]["description"]
            temperature = data["main"]["temp"]
            feels_like = data["main"]["feels_like"]
            return f"शहर **{city}** में मौसम है: **{main_weather}**, तापमान: **{temperature}°C**, महसूस हो रहा है: **{feels_like}°C**।"
        else:
            return f"शहर **{city}** का मौसम नहीं मिल पाया। कृपया सही शहर का नाम बताएं।"
    except requests.exceptions.RequestException as e:
        return f"मौसम की जानकारी प्राप्त करते समय नेटवर्क या API त्रुटि हुई: {e}"
    except KeyError:
        return f"शहर **{city}** का मौसम डेटा अमान्य है। "
    except Exception as e:
        return f"मौसम की जानकारी में कोई अज्ञात त्रुटि हुई: {e}"

# ChatGPT फ़ंक्शन
def ask_chatgpt(prompt, model="gpt-3.5-turbo"):
    """ChatGPT मॉडल से प्रश्न पूछता है।"""
    try:
        response = openai.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "आप एक सहायक AI असिस्टेंट हैं। मौसम या समय के सवालों के लिए, सीधे जानकारी देने का प्रयास करें। अगर आपको स्पष्ट रूप से शहर का नाम नहीं मिलता है, तो यूजर से पूछें।"},
                {"role": "user", "content": prompt}
            ],
            max_tokens=200,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        st.error(f"ChatGPT से पूछते समय त्रुटि हुई: {e}")
        return "ChatGPT से जवाब प्राप्त करने में असमर्थ।"

# --- Streamlit ऐप इंटरफ़ेस (UI) ---

# MIT App Inventor से आने वाली HTTP POST रिक्वेस्ट को हैंडल करें
# Streamlit POST रिक्वेस्ट को query parameters के रूप में हैंडल करता है
# इसलिए हम यहां st.experimental_get_query_params() का उपयोग कर रहे हैं
if st.experimental_get_query_params():
    query_params = st.experimental_get_query_params()

    # App Inventor से आने वाले 'action' पैरामीटर को चेक करें
    action = query_params.get('action', ['chat'])[0] # डिफॉल्ट 'chat' है

    if action == 'add_knowledge':
        question_to_add = query_params.get('question_to_add', [''])[0]
        answer_to_add = query_params.get('answer_to_add', [''])[0]
        if question_to_add and answer_to_add:
            status = add_knowledge_to_db(question_to_add, answer_to_add)
            st.json({"response": status}) # App Inventor को JSON में जवाब दें
        else:
            st.json({"response": "ज्ञान जोड़ने के लिए प्रश्न और उत्तर दोनों चाहिए।"})
    elif action == 'chat':
        user_message = query_params.get('message', [''])[0]
        # मुख्य चैटबॉट लॉजिक
        user_input_lower = user_message.lower()

        # 1. अपने खुद के डेटाबेस में देखें
        setup_database() 
        custom_answer = get_knowledge_from_db(user_message) 
        if custom_answer:
            response_text = f"मेरे ज्ञानकोष से: {custom_answer}"
        # 2. मौसम के लिए चेक करें
        elif any(keyword in user_input_lower for keyword in ["मौसम", "तापमान", "कैसा है मौसम", "वेदर", "बारिश", "जलवायु"]):
            city = None
            if "दिल्ली" in user_input_lower: city = "Delhi"
            elif "मुंबई" in user_input_lower: city = "Mumbai"
            elif "बेंगलुरु" in user_input_lower or "बेंगलुरु" in user_input_lower: city = "Bengaluru"
            elif "जयपुर" in user_input_lower: city = "Jaipur"
            elif "kota" in user_input_lower or "कोटा" in user_input_lower: city = "Kota" 
            elif "chennai" in user_input_lower or "चेन्नई" in user_input_lower: city = "Chennai"
            elif "kolkata" in user_input_lower or "कोलकाता" in user_input_lower: city = "Kolkata"

            if city:
                response_text = get_weather(city)
            else:
                response_text = "कृपया मुझे शहर का नाम बताएं जिसका मौसम आप जानना चाहते हैं।"
        # 3. समय या तारीख के लिए चेक करें
        elif "आज क्या तारीख है" in user_input_lower or "तारीख बताओ" in user_input_lower or "आज की डेट" in user_input_lower:
            now = datetime.datetime.now()
            response_text = f"आज {now.strftime('%d %B %Y')} है।" 
        elif "अभी क्या समय है" in user_input_lower or "समय बताओ" in user_input_lower or "कितने बजे हैं" in user_input_lower:
            now = datetime.datetime.now()
            response_text = f"अभी {now.strftime('%I:%M %p')} बज रहे हैं।" 
        # 4. अगर किसी विशिष्ट फ़ंक्शन से जवाब नहीं मिला, तो ChatGPT से पूछें
        else:
            chatgpt_answer = ask_chatgpt(user_message)
            if chatgpt_answer:
                response_text = f"ChatGPT से मिला: {chatgpt_answer}"
            else:
                response_text = "माफ़ करना, मैं इस सवाल का जवाब नहीं दे पा रहा हूँ।"
        st.json({"response": response_text}) # App Inventor को JSON में जवाब दें
    else:
        st.json({"response": "अवैध कार्रवाई निर्दिष्ट।"})

    # ऐप को यहीं रोक दें ताकि Streamlit UI प्रदर्शित न हो
    st.stop()


# --- यह नीचे वाला कोड केवल तब चलेगा जब कोई सीधे Streamlit URL को ब्राउज़र में खोलेगा ---
st.set_page_config(page_title="मेरा AI चैटबॉट", page_icon="🤖")
st.title("मेरा AI चैटबॉट (वेब इंटरफेस)")
st.markdown("यह इंटरफेस सीधे आपके वेब ब्राउज़र में चैट करने के लिए है। आपके App Inventor ऐप को ऊपर का लॉजिक हैंडल करेगा।")

# चैट हिस्ट्री को सेशन स्टेट में स्टोर करें ताकि पेज रीलोड होने पर भी बनी रहे
if 'messages' not in st.session_state:
    st.session_state.messages = []

# चैट हिस्ट्री दिखाएं
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# यूजर इनपुट (चैट इनपुट बॉक्स)
user_input = st.chat_input("अपना संदेश टाइप करें...")

if user_input:
    # यूजर का मैसेज जोड़ें
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # चैटबॉट से प्रतिक्रिया प्राप्त करें
    with st.spinner("सोच रहा हूँ..."): # लोडिंग इंडिकेटर दिखाएं
        # यहाँ हम chatbot_response() को सीधे कॉल कर सकते हैं क्योंकि यह ब्राउज़र इंटरफ़ेस है
        response = None # Placeholder for actual response

        # मुख्य चैटबॉट लॉजिक को दोहराएं (यह App Inventor से अलग है)
        user_input_lower_ui = user_input.lower()
        setup_database()
        custom_answer_ui = get_knowledge_from_db(user_input)
        if custom_answer_ui:
            response = f"मेरे ज्ञानकोष से: {custom_answer_ui}"
        elif any(keyword in user_input_lower_ui for keyword in ["मौसम", "तापमान", "कैसा है मौसम", "वेदर", "बारिश", "जलवायु"]):
            city_ui = None
            if "दिल्ली" in user_input_lower_ui: city_ui = "Delhi"
            elif "मुंबई" in user_input_lower_ui: city_ui = "Mumbai"
            elif "बेंगलुरु" in user_input_lower_ui or "बेंगलुरु" in user_input_lower_ui: city_ui = "Bengaluru"
            elif "जयपुर" in user_input_lower_ui: city_ui = "Jaipur"
            elif "kota" in user_input_lower_ui or "कोटा" in user_input_lower_ui: city_ui = "Kota" 
            elif "chennai" in user_input_lower_ui or "चेन्नई" in user_input_lower_ui: city_ui = "Chennai"
            elif "kolkata" in user_input_lower_ui or "कोलकाता" in user_input_lower_ui: city_ui = "Kolkata"
            if city_ui:
                response = get_weather(city_ui)
            else:
                response = "कृपया मुझे शहर का नाम बताएं जिसका मौसम आप जानना चाहते हैं।"
        elif "आज क्या तारीख है" in user_input_lower_ui or "तारीख बताओ" in user_input_lower_ui or "आज की डेट" in user_input_lower_ui:
            now = datetime.datetime.now()
            response = f"आज {now.strftime('%d %B %Y')} है।" 
        elif "अभी क्या समय है" in user_input_lower_ui or "समय बताओ" in user_input_lower_ui or "कितने बजे हैं" in user_input_lower_ui:
            now = datetime.datetime.now()
            response = f"अभी {now.strftime('%I:%M %p')} बज रहे हैं।" 
        else:
            chatgpt_answer_ui = ask_chatgpt(user_input)
            if chatgpt_answer_ui:
                response = f"ChatGPT से मिला: {chatgpt_answer_ui}"
            else:
                response = "माफ़ करना, मैं इस सवाल का जवाब नहीं दे पा रहा हूँ।"

    # चैटबॉट का मैसेज जोड़ें
    st.session_state.messages.append({"role": "assistant", "content": response})
    with st.chat_message("assistant"):
        st.markdown(response)

# ज्ञान जोड़ने का UI (साइडबार में)
st.sidebar.title("ज्ञान जोड़ें (वेब इंटरफेस)")
knowledge_q = st.sidebar.text_input("ज्ञान के लिए प्रश्न", key="knowledge_q_ui")
knowledge_a = st.sidebar.text_area("ज्ञान के लिए उत्तर", key="knowledge_a_ui")
if st.sidebar.button("ज्ञान को सहेजें (वेब)"):
    if knowledge_q and knowledge_a:
        setup_database() # सुनिश्चित करें कि DB मौजूद है
        status = add_knowledge_to_db(knowledge_q, knowledge_a)
        st.sidebar.success(status)
    else:
        st.sidebar.warning("ज्ञान जोड़ने के लिए प्रश्न और उत्तर दोनों टाइप करें।")

st.sidebar.markdown("""
---
**ध्यान दें:** यह ऐप **Streamlit Cloud** पर चल रहा है।
आपके द्वारा जोड़ा गया ज्ञान (`SQLite` डेटाबेस में) अस्थायी है और ऐप के पुनरारंभ होने पर रीसेट हो सकता है।
स्थायी ज्ञान के लिए, आपको **Google Firestore** या **PostgreSQL** जैसी ऑनलाइन डेटाबेस सेवा का उपयोग करना होगा।
""")
