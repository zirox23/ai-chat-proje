import streamlit as st
# pyrebase4'ü içe aktarıyoruz, ancak kodda pyrebase adıyla kullanmak için 'as pyrebase' ekledik.
import pyrebase4 as pyrebase 
import time
import random
import requests # API çağrısı için requests kullanıyoruz.
import json
from requests.exceptions import HTTPError, ConnectionError, Timeout

# =========================================================================
# FIREBASE KONFİGÜRASYONU VE BAĞLANTI İŞLEMLERİ
# =========================================================================

# KULLANICI TARAFINDAN SAĞLANAN GÜNCEL KONFİGÜRASYON KULLANILIYOR
FIREBASE_CONFIG = {
    "apiKey": "AIzaSyBmtvU_ceKdSXf-jVmrUPYeH1L9pDw5vdc",
    "authDomain": "digit-ai-lab.firebaseapp.com",
    "projectId": "digit-ai-lab",
    "storageBucket": "digit-ai-lab.firebasestorage.app",
    "messagingSenderId": "138611942359",
    "appId": "1:138611942359:web:086e3d048326a24a412191",
    "databaseURL": "https://digit-ai-lab-default-rtdb.firebaseio.com" 
}

# Gemini API bağlantı detayları
# ÖNEMLİ: API Key, Streamlit Secrets üzerinden veya doğrudan buraya girilmelidir. 
# Geçerli bir anahtar olmadan AI yanıtları çalışmayacaktır.
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "") # Streamlit Secrets'tan çekmeyi deneyin
if not GEMINI_API_KEY:
    # Secrets'ta yoksa, güvenlik için boş bırakılır.
    GEMINI_API_KEY = "" 
    
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent"

# Sizin AI'nızın karakterini tanımlayan sistem talimatı
SYSTEM_INSTRUCTION = """
Sen, kullanıcının web sitesindeki resmi AI asistanısın. Görevin, her zaman arkadaş canlısı, samimi ve doğal bir tonda yanıt vermek. 
Robotik dilden kaçın ve sanki bir dostunmuş gibi konuş.
Kullanıcının sorduğu detaylı sorulara (tarih, bilim, güncel olaylar vb.) cevap vermek için her zaman Google'da arama yapma yeteneğini kullan. 
Yanıtlarını daima Türkçe ver ve Türk kültürüne uygun, sıcak ifadeler kullan.
"""

# --- Firebase Bağlantı Bloğu ---
try:
    # Firebase'i pyrebase4 ile başlat
    firebase = pyrebase.initialize_app(FIREBASE_CONFIG)
    auth = firebase.auth()
    db = firebase.database()
    st.session_state['firebase_connected'] = True
except Exception as e:
    # Streamlit Cloud'da bağlantı hatalarını göster
    st.error(f"❌ Firebase bağlantı hatası: Konfigürasyonunuzu kontrol edin. Hata: {e}")
    st.session_state['firebase_connected'] = False
    
    class DummyAuth:
        """Firebase'e bağlanılamadığında sahte Auth metotları sağlar."""
        def create_user_with_email_and_password(self, email, password): 
            raise Exception("Auth Error: Bağlantı Başarısız")
        def sign_in_with_email_and_password(self, email, password): 
            raise Exception("Auth Error: Bağlantı Başarısız")
        def current_user(self):
            return None
    
    auth = DummyAuth()
    
# =========================================================================
# DURUM YÖNETİMİ VE SABİTLER
# =========================================================================

TRIAL_DURATION = 120 # Deneme süresi (saniye)

if 'is_loaded' not in st.session_state:
    st.session_state.is_loaded = False
if 'user_info' not in st.session_state:
    st.session_state.user_info = None
if 'trial_end_time' not in st.session_state:
    st.session_state.trial_end_time = time.time() + TRIAL_DURATION 
if 'messages' not in st.session_state:
    # Her yeni oturumda AI'ın ilk mesajı
    st.session_state.messages = [{"role": "assistant", "content": "Selamlar! Ben senin AI arkadaşınım. Nasılsın bakalım? Aklına takılan her şeyi bana sorabilirsin."}]
if 'message_count' not in st.session_state:
    st.session_state.message_count = 0


# =========================================================================
# YAPAY ZEKA MANTIĞI VE SOHBET YANITLARI (GEMINI API İLE)
# =========================================================================

def format_sources(sources):
    """Kaynaktan gelen bilgileri Markdown formatında düzenler."""
    if not sources:
        return ""
    
    source_list = "\n\n**Kaynaklar:**\n"
    for i, source in enumerate(sources):
        if source.get('uri') and source.get('title'):
            # Güvenlik ve temizlik için başlığı kısaltabiliriz
            title = source['title'][:100] + ('...' if len(source['title']) > 100 else '')
            # URL'i temizleyip Markdown linki olarak döndür
            source_list += f"{i+1}. [{title}]({source['uri'].replace(' ', '%20')})\n"
    return source_list

def generate_ai_response(prompt):
    """
    Google Search grounding kullanarak gerçek yapay zeka yanıtı üretir (API çağrısı).
    requests kütüphanesi ve gelişmiş hata yönetimi kullanır.
    """
    
    if not GEMINI_API_KEY:
        return "Hey! AI Anahtarı (API Key) eksik olduğu için Google'a bağlanamıyorum. Şimdilik sadece basit, önceden tanımlanmış yanıtlar verebilirim."
        
    chat_history = []
    # Sohbet geçmişini API için hazırlar. Kaynakları mesajlardan ayırır.
    for message in st.session_state.messages:
        content = message["content"].split("\n\n**Kaynaklar:**")[0] 
        role = "model" if message["role"] == "assistant" else message["role"] 
        chat_history.append({"role": role, "parts": [{"text": content}]})

    # Yeni kullanıcı prompt'unu sohbete ekler
    contents_for_api = chat_history + [{"role": "user", "parts": [{"text": prompt}]}]

    payload = {
        "contents": contents_for_api, 
        "tools": [{"google_search": {} }], # Arama yapma yeteneğini etkinleştir
        "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]}
    }

    url = f"{GEMINI_API_URL}?key={GEMINI_API_KEY}"
    headers = {'Content-Type': 'application/json'}

    try:
        # requests ile POST isteği oluşturma
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status() # HTTP hatalarını yakalamak için

        result = response.json()
        
        candidate = result.get('candidates', [{}])[0]
        text = candidate.get('content', {}).get('parts', [{}])[0].get('text', 'Üzgünüm, yanıt oluşturulamadı.')

        # Kaynakları çıkar
        sources = []
        grounding_metadata = candidate.get('groundingMetadata')
        if grounding_metadata and grounding_metadata.get('groundingAttributions'):
            sources = [
                {'uri': attr.get('web', {}).get('uri'), 'title': attr.get('web', {}).get('title')}
                for attr in grounding_metadata['groundingAttributions']
            ]
        
        # Yanıtı ve kaynakları birleştirip döndür
        return text + format_sources(sources)

    except HTTPError as e:
        # HTTP 4xx, 5xx hataları (örn: 400 Bad Request, 403 Forbidden, 429 Rate Limit, 500 Internal Server Error)
        return f"Hey! Dış dünyadan bilgi çekerken API'de bir sorun çıktı (HTTP Hata Kodu: {e.response.status_code}). Sanırım AI anahtarı (API Key) eksik veya geçersiz olabilir. Şimdilik basit sohbet edelim mi?"
    except ConnectionError:
        # Ağ bağlantısı hataları
        return "İnternetim çekmiyor galiba! Şu an Google'a bağlanıp detaylı bilgi alamıyorum. Lütfen ağ bağlantınızı kontrol edin. Basit sohbet edelim, olur mu?"
    except Timeout:
        # Zaman aşımı hatası
        return "AI çok düşündü ama yanıtı zamanında yetiştiremedi. Lütfen tekrar deneyin."
    except Exception as e:
        # Genel iç hatalar (JSON parse etme, vs.)
        st.error(f"AI İç Hata: {e}")
        return "Bende beklenmedik bir hata oluştu! Bir mühendis çağırmam gerekebilir. Kusura bakma."


# =========================================================================
# DİĞER FONKSİYONLAR 
# =========================================================================

def display_splash_screen():
    """Hızlı yükleme ekranını (splash screen) gösterir."""
    with st.empty():
        st.title("🚀 Yapay Zeka Sistemi Yükleniyor...")
        st.info("Kütüphaneler yüklenirken lütfen bekleyin.")
        
        try:
            for percent_complete in range(1, 11): 
                time.sleep(0.15)
                st.progress(percent_complete * 10, text=f"Modül yükleniyor: {percent_complete * 10}%")

            st.success("Yükleme Tamamlandı! Uygulama Başlatılıyor...")
            time.sleep(1) 

            st.session_state.is_loaded = True
            st.rerun() 

        except Exception as e:
            st.error(f"Model veya Kütüphane Yükleme Hatası: {e}")


def handle_chat_input():
    """Kullanıcı mesajını işler ve sohbete ekler."""
    user_prompt = st.session_state.prompt
    if user_prompt:
        # 1. Kullanıcı mesajını ekle
        st.session_state.messages.append({"role": "user", "content": user_prompt})
        
        # 2. Yanıtı üretmek için bekleme animasyonu
        # Yeni bir anahtar kullan (spinner_key) ve eski mesajları temizleme
        with st.spinner("🤖 Bir saniye, yanıtınızı arkadaşça bir dille hazırlıyorum..."):
            # Gerçek API çağrısı
            ai_response = generate_ai_response(user_prompt)
            # Düşünme süresi eklenir, böylece yapay zekanın yanıtı hemen gelmez
            time.sleep(random.uniform(1.0, 2.5)) 

        # 3. Cevabı sohbete ekle
        st.session_state.messages.append({"role": "assistant", "content": ai_response})
        st.session_state.message_count += 1
        
        # 4. Giriş alanını temizle ve arayüzü yenile
        st.session_state.prompt = ""
        st.rerun()

def draw_chat_interface():
    """Sohbet geçmişini ve giriş alanını çizer."""
    
    # Sohbet geçmişini göstermek için bir konteyner kullanıyoruz.
    # Bu, 'removeChild' hatalarını önlemede yardımcı olur.
    chat_container = st.container(height=450, border=True)
    with chat_container:
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

    # Sohbet girişini aşağıda çiz
    if is_trial_active() or st.session_state.user_info:
        st.chat_input("Buraya mesajınızı arkadaşınıza yazar gibi yazın...", key="prompt", on_submit=handle_chat_input)
    else:
        st.info("Ücretsiz deneme süreniz doldu. Devam etmek için lütfen Kayıt Olun/Giriş Yapın.")


def is_trial_active():
    """Deneme süresinin aktif olup olmadığını kontrol eder."""
    return time.time() < st.session_state.trial_end_time

def get_remaining_time():
    """Kalan deneme süresini hesaplar."""
    remaining_seconds = int(st.session_state.trial_end_time - time.time())
    if remaining_seconds < 0:
        return 0
    return remaining_seconds

def draw_sidebar():
    """Kenar çubuğunu (Sidebar) çizer ve Auth/Zamanlayıcıyı yönetir."""
    with st.sidebar:
        st.header("👤 Kullanıcı Durumu")
        
        if st.session_state.user_info:
            st.success(f"✅ Giriş Yapıldı: {st.session_state.user_info['email']}")
            st.button("Çıkış Yap", on_click=logout)
        
        else:
            remaining = get_remaining_time()
            if remaining > 0:
                st.warning(f"⏳ Kayıt Gerekli: {remaining} saniye kaldı.")
            else:
                st.error("🔒 Deneme Süreniz Doldu. Lütfen Kayıt Olun/Giriş Yapın.")
            
            st.subheader("Giriş / Kayıt")
            secim = st.selectbox("İşlem Seçin:", ["Giriş Yap", "Kayıt Ol"], key="auth_select")
            
            if secim == "Kayıt Ol":
                email = st.text_input("E-posta Adresi", key="reg_email")
                password = st.text_input("Şifre", type="password", key="reg_pass")
                if st.button("Kayıt Ol", use_container_width=True):
                    register_user(email, password)

            elif secim == "Giriş Yap":
                email = st.text_input("E-posta Adresi", key="login_email")
                password = st.text_input("Şifre", type="password", key="login_pass")
                if st.button("Giriş Yap", use_container_width=True):
                    login_user(email, password)

# --- AUTH İşlemleri ---
def register_user(email, password):
    """Kullanıcı kayıt işlemini gerçekleştirir."""
    if st.session_state.firebase_connected:
        try:
            user = auth.create_user_with_email_and_password(email, password)
            st.session_state.user_info = user
            st.success(f"Kayıt Başarılı! Kullanıcı: {user['email']}")
            st.rerun()
        except Exception as e:
            st.error(f"Kayıt Hatası: {e}")
            st.error("Lütfen: 1) E-posta/Şifre biçimini kontrol edin. 2) Firebase konsolunda **Authentication (Kimlik Doğrulama)** ayarlarını açtığınızdan emin olun.")
    else:
        st.error("Firebase'e bağlanılamadığı için kayıt yapılamıyor.")

def login_user(email, password):
    """Kullanıcı giriş işlemini gerçekleştirir."""
    if st.session_state.firebase_connected:
        try:
            user = auth.sign_in_with_email_and_password(email, password)
            st.session_state.user_info = user
            st.success(f"Giriş Başarılı! Kullanıcı: {user['email']}")
            st.rerun()
        except Exception as e:
            st.error(f"Giriş Hatası: {e}")
    else:
        st.error("Firebase'e bağlanılamadığı için giriş yapılamıyor.")

def logout():
    """Çıkış işlemini gerçekleştirir."""
    st.session_state.user_info = None
    # Çıkış yapıldığında sohbeti sıfırla
    st.session_state.messages = [{"role": "assistant", "content": "Görüşmek üzere! Yeni bir oturum başlattın. Nasılsın?"}]
    st.session_state.trial_end_time = time.time() + TRIAL_DURATION 
    st.success("Başarıyla çıkış yaptınız.")
    st.rerun()


# =========================================================================
# ANA UYGULAMA AKIŞI
# =========================================================================

def run_app():
    """Uygulamanın ana döngüsüdür."""
    st.set_page_config(layout="wide", page_title="AI Sohbet Sistemi")
    
    if not st.session_state.is_loaded:
        display_splash_screen()
        return

    st.title("🤝 Yapay Zeka Arkadaşın")
    
    draw_sidebar()
    
    if st.session_state.user_info or is_trial_active():
        st.subheader("💬 AI Sohbet Alanı (Gizliliğin Ön Planda)")
        st.info("Unutma: Sohbet geçmişin bu oturumda kalıyor. Rahatça konuşabilirsin!")
        draw_chat_interface()
    else:
        st.subheader("⚠️ Erişim Kısıtlandı")
        st.warning("Ücretsiz deneme süreniz sona erdi. Sohbeti kullanmaya devam etmek için lütfen soldaki menüden Kayıt Olun veya Giriş Yapın.")


if __name__ == '__main__':
    run_app()
