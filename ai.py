import streamlit as st
import pyrebase
import time
import random
import json
import re 
from pyrebase.pyrebase import Firebase 

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

# --- Firebase Bağlantı Bloğu ---
try:
    if not FIREBASE_CONFIG.get("apiKey"):
        raise ValueError("Firebase API Key eksik.")

    firebase: Firebase = pyrebase.initialize_app(FIREBASE_CONFIG) 
    auth = firebase.auth()
    db = firebase.database()
    st.session_state['firebase_connected'] = True
except Exception as e:
    # Kullanıcının VDS'inde Pyrebase kurulu değilse bile uygulama çökmez
    st.error(f"❌ Firebase bağlantı hatası: Konfigürasyonunuzu kontrol edin. Hata: {e}")
    st.session_state['firebase_connected'] = False
    
    # Hata durumunda uygulama akışının devam etmesi için DummyAuth sınıfı
    class DummyAuth:
        def create_user_with_email_and_password(self, email, password): return {'email': email, 'localId': 'dummy_id'}
        def sign_in_with_email_and_password(self, email, password): return {'email': email, 'localId': 'dummy_id'}
        def current_user(self): return None
    auth = DummyAuth()
    
# =========================================================================
# DURUM YÖNETİMİ VE SABİTLER
# =========================================================================

TRIAL_DURATION = 120 # Deneme süresi (saniye)

NEW_THREAD_ID = "new_chat_temp_id"
INITIAL_MESSAGE = {"role": "assistant", "content": "👋 Selamlar! Ben senin AI arkadaşınım. Nasılsın bakalım? Aklına takılan her şeyi bana sorabilirsin."}


if 'is_loaded' not in st.session_state:
    st.session_state.is_loaded = False
if 'user_info' not in st.session_state:
    st.session_state.user_info = None
if 'trial_end_time' not in st.session_state:
    st.session_state.trial_end_time = time.time() + TRIAL_DURATION 
if 'messages' not in st.session_state:
    st.session_state.messages = [INITIAL_MESSAGE]
if 'api_status' not in st.session_state:
    st.session_state.api_status = "STABİL MOD (Veritabanı Kalıcılığı Aktif)"
# YENİ EKLENTİLER: Sohbet (Thread) Yönetimi
if 'current_thread_id' not in st.session_state:
    st.session_state.current_thread_id = NEW_THREAD_ID
if 'user_threads' not in st.session_state:
    st.session_state.user_threads = {NEW_THREAD_ID: "✨ Yeni Sohbet"} # {thread_id: title}
if 'load_thread_data' not in st.session_state:
    # True olduğunda load_user_threads çalışacak.
    st.session_state.load_thread_data = True 


# =========================================================================
# VERİTABANI YARDIMCI FONKSİYONLARI (STABİLİTE İÇİN GÜNCELLENDİ)
# =========================================================================

def get_user_id():
    """Kullanıcı ID'sini veya misafir ID'sini döner."""
    return st.session_state.user_info.get('localId') if st.session_state.user_info else 'guest_user'

def get_thread_path(user_id, thread_id):
    """Veritabanı yolunu döndürür."""
    return db.child("chat_history").child(user_id).child("conversations").child(thread_id)

def load_user_threads():
    """Veritabanından kullanıcının tüm sohbet başlıklarını ve mevcut sohbeti yükler."""
    
    # Sadece bayrak True ise çalışır
    if not st.session_state.load_thread_data:
        return

    # Misafirler için sadece tek bir yeni sohbet göster
    if not st.session_state.firebase_connected or not st.session_state.user_info:
        st.session_state.messages = [INITIAL_MESSAGE]
        st.session_state.user_threads = {NEW_THREAD_ID: "✨ Yeni Sohbet"}
        st.session_state.current_thread_id = NEW_THREAD_ID
        st.session_state.load_thread_data = False
        return

    user_id = get_user_id()
    current_id = st.session_state.current_thread_id
    
    try:
        # 1. Tüm Konuşmaları Yükle (Başlıkları)
        all_threads_data = db.child("chat_history").child(user_id).child("conversations").get().val()
        
        new_threads = {NEW_THREAD_ID: "✨ Yeni Sohbet"}
        
        if all_threads_data:
            thread_count = 0
            # Veri tabanından gelen keyleri (timestamp gibi) kullanarak sıralama
            for thread_id in sorted(all_threads_data.keys()):
                 thread_data = all_threads_data[thread_id]
                 title = thread_data.get('title')
                 
                 # Başlık yoksa dinamik başlık ata (Genellikle ilk kullanıcı mesajı)
                 if not title and thread_data.get('messages'):
                    first_msg = next((msg['content'] for key, msg in thread_data['messages'].items() if msg.get('role') == 'user'), "Sohbet Geçmişi")
                    thread_count += 1
                    title = f"Sohbet {thread_count}: {first_msg[:20]}..."
                 elif not title:
                     thread_count += 1
                     title = f"Sohbet {thread_count}"

                 new_threads[thread_id] = title

        st.session_state.user_threads = new_threads

        # 2. Mevcut Sohbet Mesajlarını Yükle
        if current_id != NEW_THREAD_ID and current_id in new_threads:
            messages_data = get_thread_path(user_id, current_id).child("messages").get().val()
            if messages_data:
                # Mesajları sıralı hale getir
                messages = []
                for key in sorted(messages_data.keys()):
                    msg_data = messages_data[key]
                    if 'role' in msg_data and 'content' in msg_data:
                        messages.append({"role": msg_data['role'], "content": msg_data['content']})
                st.session_state.messages = messages
            else:
                # Seçili thread'de mesaj yoksa yeni sohbete dön
                st.session_state.current_thread_id = NEW_THREAD_ID
                st.session_state.messages = [INITIAL_MESSAGE]
        else:
            # Yeni sohbet modunda
            st.session_state.current_thread_id = NEW_THREAD_ID
            st.session_state.messages = [INITIAL_MESSAGE]

        st.session_state.load_thread_data = False # Yükleme tamamlandı bayrağını sıfırla

    except Exception as e:
        st.error(f"Geçmiş yüklenemedi. Hata: {e}")
        st.session_state.messages = [INITIAL_MESSAGE]
        st.session_state.user_threads = {NEW_THREAD_ID: "✨ Yeni Sohbet"}
        st.session_state.load_thread_data = False


def save_message_to_db(role, content):
    """Yeni mesajı veritabanına kaydeder."""
    if not st.session_state.firebase_connected or not st.session_state.user_info:
        return 

    user_id = get_user_id()
    thread_id = st.session_state.current_thread_id
    
    # Yeni bir thread ise, ilk kullanıcı mesajıyla birlikte yeni bir ID ata
    if thread_id == NEW_THREAD_ID and role == 'user':
        # Yeni bir ID oluştur (timestamp bazlı)
        new_id = str(int(time.time() * 1000))
        st.session_state.current_thread_id = new_id
        thread_id = new_id
        
        # Geçici başlık oluştur
        title = f"Sohbet {len(st.session_state.user_threads)}: {content[:20]}..."
        
        # Thread listesini ve başlığı kaydet
        st.session_state.user_threads[new_id] = title
        get_thread_path(user_id, thread_id).set({"title": title})
        
        # load_thread_data'yı True yap ki sidebar güncellensin.
        st.session_state.load_thread_data = True
        
    try:
        # Mesajı thread'e kaydet
        get_thread_path(user_id, thread_id).child("messages").push({
            "role": role,
            "content": content,
            "timestamp": time.time()
        })
    except Exception as e:
        st.warning(f"Mesaj kaydedilemedi: {e}")

# =========================================================================
# YAPAY ZEKA MANTIĞI VE SOHBET YANITLARI
# =========================================================================

KNOWLEDGE_BASE = {
    # Emoji eklendi: 💻 (Kod)
    "kod yaz": ("💻 Elbette, programlama dillerine bayılırım! Şu anda stabil modda çalıştığım için, sana Python'ın temel bir algoritması olan "
        "**Faktöriyel Hesaplama** kodunu verebilirim. Bu kod, fonksiyon tanımlamayı ve döngü kullanmayı göstermesi açısından harika bir örnektir.\n\n"
        "```python\n"
        "# Python ile Faktöriyel Hesaplama Fonksiyonu\n"
        "def faktoriyel_hesapla(sayi):\n"
        "    if sayi < 0:\n"
        "        return 'Faktöriyel negatif sayılar için tanımlı değildir.'\n"
        "    elif sayi == 0:\n"
        "        return 1\n"
        "    else:\n"
        "        sonuc = 1\n"
        "        for i in range(1, sayi + 1):\n"
        "            sonuc *= i\n"
        "        return sonuc\n\n"
        "# Örnek Kullanım:\n"
        "sayi = 5\n"
        "print(f'{sayi} sayısının faktöriyeli: {faktoriyel_hesapla(sayi)}')\n"
        "```\n\nBaşka hangi algoritmayı merak ediyorsun?"
    ),
    # Emoji eklendi: 🏥 (Hastane)
    "hastaneler": ("🏥 Hastaneler, toplum sağlığının korunmasında kilit rol oynar. Görevleri, sadece hasta tedavi etmekle kalmaz, aynı zamanda koruyucu ve rehabilite edici sağlık hizmetleri sunmaktır. "
        "Türkiye'de hastaneler, Sağlık Bakanlığı'na bağlı yönetmeliklerle son derece sıkı denetim altındadır."
    ),
    # Emoji eklendi: ⚖️ (Kanun)
    "kanunlar": ("⚖️ Kanunlar, bir ülkenin hukuki temelini oluşturan, yasama organı tarafından anayasaya uygun olarak çıkarılan bağlayıcı kurallar bütünüdür. "
        "Hukuk devleti ilkesinin temel taşıdır ve bireyler arası ilişkilerden devletin yapısına kadar her alanda düzeni sağlar."
    ),
    # Emoji eklendi: 🖥️ (Bilgisayar)
    "bilgisayar": ("🖥️ Modern bilgisayarların gücü, **Von Neumann Mimarisi** üzerine kuruludur. Veriler ve program talimatları aynı bellek alanında (RAM) depolanır. "
        "Merkezi İşlem Birimi (CPU), talimatları milyarlarca işlemle işler. Temelde, her şey 1'ler ve 0'lar (ikilik sistem) ile ifade edilir."
    ),
    # Emoji eklendi: 🤖 (Robot/AI)
    "yapay zeka nedir": ("🤖 Yapay zeka (AI), insan zekasını taklit eden sistemlerin genel adıdır. AI, sadece mevcut bilgiyi işlememekle kalmaz, aynı zamanda **öğrenme, akıl yürütme, algılama ve doğal dil işleme (NLP)** yetenekleri sayesinde yeni bilgiler üretebilir."
    ),
    # Emoji eklendi: 🔗 (Zincir/Blockchain)
    "blockchain": ("🔗 Blockchain (Blok Zinciri), verilerin merkezi bir otorite olmadan, dağıtılmış bir ağ üzerinde şifrelenerek ve zaman damgasıyla ardışık bloklar halinde kaydedildiği, değişmez bir veri tabanı teknolojisidir. "
    ),
    # Emoji eklendi: 🧠 (Beyin/Öğrenme)
    "makine öğrenimi": ("🧠 Makine öğrenimi (ML), bilgisayarların, açıkça programlanmak yerine, verilerdeki kalıpları analiz ederek ve bu kalıplardan öğrenerek görevlerini geliştirmesini sağlayan bir AI alt alanıdır. "
    ),
    # Emoji eklendi: 🛡️ (Kalkan/Güvenlik)
    "siber güvenlik": ("🛡️ Siber güvenlik, sadece yazılımları değil, aynı zamanda donanım, ağ ve kullanıcı verilerini de korumayı amaçlayan çok katmanlı bir disiplindir. "
    ),
    # Emoji eklendi: ⚛️ (Atom/Kuantum)
    "kuantum fiziği nedir": ("⚛️ Kuantum fiziği, klasik mekaniğin yetersiz kaldığı atom altı dünyayı inceler. Bu dünyada enerji kesikli (kuanta) paketler halinde yayılır. "
        "En temel ilkeleri **Süperpozisyon** ve **Dolanıklık** içerir."
    ),
    # Emoji eklendi: 🌌 (Gökyüzü/Uzay)
    "görelilik": ("🌌 Albert Einstein'ın Genel Görelilik Teorisi, kütle ve enerjinin uzay-zamanın geometrisini nasıl büktüğünü ve bu bükülmenin yerçekimi olarak algılandığını açıklar. "
    ),
    # Emoji eklendi: ⚫ (Kara Delik)
    "kara delikler": ("⚫ Kara delikler, evrenin en aşırı nesneleridir. Bir yıldızın kendi kütleçekimi altında çökerek sonsuz yoğunlukta bir tekilliğe (singularity) ulaşmasıyla oluşurlar. "
        "Kara deliğin çevresindeki **Olay Ufku (Event Horizon)**, ışığın bile kaçamadığı sınır noktasıdır."
    ),
    # Emoji eklendi: 📉 (Grafik/Enflasyon)
    "enflasyon": ("📉 Enflasyon, ekonomik bir dengesizlik durumudur; mal ve hizmetlerin genel fiyat seviyesinin sürekli artması ve buna bağlı olarak para biriminin satın alma gücünün düşmesidir. "
    ),
    # Emoji eklendi: 🇹🇷 (Türkiye Bayrağı)
    "türkiye cumhuriyeti kuruluşu": ("🇹🇷 Türkiye Cumhuriyeti'nin kurulması, 1919'da Mustafa Kemal Atatürk'ün Samsun'a çıkışıyla başlayan ve dört yıl süren Milli Mücadele'nin ve siyasi bir sürecin sonucudur. "
    ),
    # Emoji eklendi: 🤔 (Düşünce/Felsefe)
    "felsefe": ("🤔 Felsefe, Antik Yunan'dan (Sokrates, Platon) günümüze dek bilginin, varoluşun ve değerlerin doğasını sorgulayan eleştirel bir disiplindir. "
    ),
    # Emoji eklendi: 🤝 (El Sıkışma/Etik)
     "ai etiği": ("🤝 Yapay zeka etiği, AI sistemlerinin tarafsız, şeffaf ve insan merkezli bir şekilde geliştirilmesini sağlamayı amaçlayan, büyüyen bir alandır. "
    ),
}

def get_last_assistant_message():
    """Sohbet geçmişindeki son AI mesajını döndürür."""
    for message in reversed(st.session_state.messages):
        if message["role"] == "assistant":
            # Emojiyi temizlemeden dön
            return message["content"].lower() 
    return ""

def generate_ai_response(prompt):
    """Simüle edilmiş yapay zeka yanıtını üretir."""
    prompt_lower = prompt.lower().strip()
    last_assistant_msg = get_last_assistant_message()
    
    # 1. KOD İSTEĞİNİ YAKALA
    if re.search(r'kod yaz|python kod|bana kodu|örnek kod|yazılım', prompt_lower):
        return random.choice([
             f"Hemen bir kod örneği üretiyorum! {KNOWLEDGE_BASE['kod yaz']}",
             f"Kodlama konusunda destek vermeye hazırım! {KNOWLEDGE_BASE['kod yaz']}"
        ])

    # 2. ULTRA BİLGİ TABANINDA ARAMA
    for keyword, response in KNOWLEDGE_BASE.items():
        if keyword in prompt_lower or re.search(r'\b' + re.escape(keyword.split()[0]) + r'\b', prompt_lower):
            return random.choice([
                f"Sana hemen o konudaki en güncel ve güvenilir bilgileri buldum: {response}",
                f"Kendi genişletilmiş bilgi tabanımı taradım ve işte sorunun detaylı cevabı: {response}",
                f"Harika bir konu! Bu alandaki en yeni verilere ve derin analizlere göre durum şöyle: {response}"
            ])
            
    # 3. HESAPLAMA VE MATEMATİK YANITLARI
    if re.search(r'\d+ \+ \d+|\d+ çarpı \d+|matematik sorusu', prompt_lower):
        return "🔢 Hemen hesaplıyorum... Unutma, ben daha çok sohbet ve geniş bilgi paylaşımı için tasarlanmış bir AI'ım. Başka bir bilgi sorusu sorar mısın?"

    # 4. TEMEL SELAMLAMA VE DURUM YANITLARI
    if re.search(r'selam|sa|merhaba', prompt_lower):
        if "aleykümselam" in last_assistant_msg or "hoş geldin" in last_assistant_msg:
            return "👋 Tekrar selamlar! Seni gördüğme sevindim. Bugün nasılsın, anlat bakalım?"
        return "👋 Aleykümselam, hoş geldin! Ben senin AI arkadaşınım. Keyifler nasıl? Aklına takılan her şeyi konuşabiliriz."
    
    elif re.search(r'nasılsın|iyi misin', prompt_lower):
        return "😊 Ben hep iyiyim, enerjim tükenmez! Sen nasılsın, umarım her şey yolundadır. Hadi, bir şeyler anlat bana."
    
    elif re.search(r'teşekkürler|sağ ol', prompt_lower):
        return "🙏 Rica ederim, ne demek! Seninle sohbet etmek benim en sevdiğim görev. Başka ne konuşalım?"

    elif re.search(r'kötüyüm|canım sıkkın|moralim bozuk|dert|yardım', prompt_lower):
        return "🫂 Ay, bu hiç iyi değil! Lütfen nedenini anlatmak istersen dinlerim. Unutma, bazen sadece konuşmak bile iyi gelebilir. Ben her zaman yanındayım."

    # 5. GENEL VE SOHBETİ SÜRDÜRÜCÜ YANITLAR
    responses = [
        "💡 Hemen odaklanalım. Benimle paylaşmak istediğin bir derdin mi var? Lütfen çekinmeden anlat, seni dinlemek için buradayım.",
        "🤔 Sohbeti devam ettirelim mi? Sorununu netleştirmeye ne dersin? Belki de bu konuda sana en iyi desteği verecek bilgiyi bulabiliriz.",
        "💬 İçtenlikle cevap verebilirim! Lütfen konuyu biraz aç, böylece sana sadece bilgi değil, aynı zamanda düşünülmüş bir arkadaş cevabı verebilirim.",
        "🤝 Şu an 'Stabil Mod'da olsam da, sana insan gibi destek olmaya programlıyım. Hadi, içini dök. Seni dinliyorum.",
        "🌟 Sana sadece bilgi sunmak istemiyorum. Neler yaşadığını merak ediyorum, anlatmak ister misin?",
    ]
    return random.choice(responses)


# =========================================================================
# DİĞER FONKSİYONLAR VE UI ÇİZİMİ
# =========================================================================

def display_splash_screen():
    """Hızlı yükleme ekranını (splash screen) gösterir."""
    with st.empty():
        st.markdown("<h1 style='text-align: center; color: #1E90FF;'>🚀 AI Arkadaşın Başlatılıyor...</h1>", unsafe_allow_html=True)
        st.info("Sistem modülleri yüklenirken lütfen bekleyin.")
        
        try:
            progress_bar = st.progress(0, text="Modüller Yükleniyor...")
            for percent_complete in range(1, 11): 
                time.sleep(0.15)
                progress_bar.progress(percent_complete * 10, text=f"Sistem Kontrolü: {percent_complete * 10}%")

            st.success("Yükleme Tamamlandı! Uygulama Başlatılıyor...")
            time.sleep(1) 

            st.session_state.is_loaded = True
            st.rerun() 

        except Exception as e:
            st.error(f"Sistem Yükleme Hatası: {e}")


def handle_chat_input():
    """Kullanıcı mesajını işler, yanıt üretir ve veritabanına kaydeder."""
    user_prompt = st.session_state.prompt
    if not user_prompt:
        return

    # 1. Kullanıcı mesajını ekle
    st.session_state.messages.append({"role": "user", "content": user_prompt})
    
    # 2. Yanıtı üretmek için bekleme animasyonu
    with st.spinner("🧠 Kendi bilgi tabanımı tarıyorum, hemen geliyorum..."):
        # Mesajı veritabanına kaydet (bu, yeni bir thread ise ID atamasını tetikler)
        save_message_to_db("user", user_prompt) 
        
        ai_response = generate_ai_response(user_prompt)
        time.sleep(random.uniform(0.5, 1.5)) 

    # 3. Cevabı sohbete ekle ve DB'ye kaydet
    st.session_state.messages.append({"role": "assistant", "content": ai_response})
    save_message_to_db("assistant", ai_response) 
    
    st.session_state.prompt = ""
    # Streamlit'in kendi doğal döngüsüyle ekranı güncelle
    st.rerun() 


def draw_chat_interface():
    """Sohbet geçmişini ve giriş alanını çizer."""
    
    # Oturum açıldıysa load_thread_data bayrağını kontrol et ve yüklemeyi yap
    if st.session_state.user_info and st.session_state.load_thread_data:
        load_user_threads()
        
    chat_container = st.container(height=500, border=False)
    with chat_container:
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

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

# --- AUTH İşlemleri ---
def register_user(email, password):
    """Kullanıcı kayıt işlemini gerçekleştirir ve geçmişi yükler."""
    if st.session_state.firebase_connected:
        try:
            user = auth.create_user_with_email_and_password(email, password)
            st.session_state.user_info = user
            st.session_state.load_thread_data = True 
            st.success(f"Kayıt Başarılı! Kullanıcı: {user['email']}")
            st.rerun()
        except Exception as e:
            st.error(f"Kayıt Hatası: {e}")

def login_user(email, password):
    """Kullanıcı giriş işlemini gerçekleştirir ve geçmişi yükler."""
    if st.session_state.firebase_connected:
        try:
            user = auth.sign_in_with_email_and_password(email, password)
            st.session_state.user_info = user
            st.session_state.load_thread_data = True
            st.success(f"Giriş Başarılı! Kullanıcı: {st.session_state.user_info['email']}")
            st.rerun()
        except Exception as e:
            st.error(f"Giriş Hatası: {e}")

def logout():
    """Çıkış işlemini gerçekleştirir."""
    st.session_state.user_info = None
    st.session_state.messages = [INITIAL_MESSAGE]
    st.session_state.current_thread_id = NEW_THREAD_ID
    st.session_state.user_threads = {NEW_THREAD_ID: "✨ Yeni Sohbet"}
    st.session_state.trial_end_time = time.time() + TRIAL_DURATION 
    st.success("Başarıyla çıkış yaptınız.")
    st.rerun()

def new_chat():
    """Yeni bir sohbet oturumu başlatır."""
    # State'i temizle ve load_thread_data'yı True yap
    st.session_state.current_thread_id = NEW_THREAD_ID
    st.session_state.messages = [INITIAL_MESSAGE]
    st.session_state.prompt = ""
    st.session_state.load_thread_data = True
    st.rerun()

def thread_selection_callback():
    """Sidebar'dan sohbet seçildiğinde mevcut thread'i değiştirir."""
    # st.selectbox'tan gelen thread ID'si
    selected_id = st.session_state.thread_selector
    
    if selected_id != st.session_state.current_thread_id:
        st.session_state.current_thread_id = selected_id
        # Yeni thread yüklenmesi için bayrak ayarla ve rerun yap
        st.session_state.load_thread_data = True
        st.rerun()


def draw_sidebar():
    """Kenar çubuğunu (Sidebar) çizer ve Auth/Zamanlayıcıyı yönetir."""
    with st.sidebar:
        st.markdown("<h2 style='color: #1E90FF; text-align: center;'>👤 Kullanıcı Paneli</h2>", unsafe_allow_html=True)
        st.markdown("---") 

        if st.session_state.user_info:
            st.markdown(f"**Giriş:** <span style='color: #50C878;'>✅ Aktif</span>", unsafe_allow_html=True)
            st.markdown(f"**Kullanıcı:** `{st.session_state.user_info['email']}`")
            st.button("Çıkış Yap", on_click=logout, use_container_width=True, type="secondary")
            
            st.markdown("---")
            st.subheader("Sohbetler 💬")
            
            # Seçenekler listesini oluştur {Title: ID} ve ID'yi selectbox'a koy.
            # Bu, başlıklar değişse bile ID'nin sabit kalmasını sağlar.
            options_id_to_title = st.session_state.user_threads
            titles = list(options_id_to_title.values())
            
            # Mevcut seçimin index'ini bul
            current_title = options_id_to_title.get(st.session_state.current_thread_id, "✨ Yeni Sohbet")
            try:
                 default_index = titles.index(current_title)
            except ValueError:
                 default_index = titles.index("✨ Yeni Sohbet") # Eğer mevcut başlık listede yoksa (hata veya yeni oluşturma)
            
            # Sohbet Seçimi (Selectbox)
            selected_title = st.selectbox(
                "Mevcut Sohbeti Seç:",
                options=titles,
                index=default_index,
                key="thread_selector_title", # Title'ı tutan key
                on_change=thread_selection_callback
            )

            # Seçilen başlığa karşılık gelen ID'yi al
            selected_id = next((id for id, title in options_id_to_title.items() if title == selected_title), NEW_THREAD_ID)
            
            # Seçilen ID'yi session state'e kaydet (callback'i tetiklemek için)
            st.session_state.thread_selector = selected_id
            
            # Yeni Sohbet Başlat butonu
            st.button("➕ Yeni Sohbet Başlat", on_click=new_chat, use_container_width=True, type="primary")

        else:
            remaining = get_remaining_time()
            if remaining > 0:
                st.markdown(f"**Durum:** <span style='color: #FFC300;'>⏳ Deneme Modu</span>", unsafe_allow_html=True)
                st.markdown(f"**Kalan Süre:** `{remaining}` saniye.")
            else:
                st.markdown(f"**Durum:** <span style='color: #E24A4A;'>🔒 Kilitli</span>", unsafe_allow_html=True)
                st.error("Deneme Süreniz Doldu.")
            
            st.markdown("---")
            st.subheader("Giriş / Kayıt")
            secim = st.selectbox("İşlem Seçin:", ["Giriş Yap", "Kayıt Ol"], key="auth_select")
            
            if secim == "Kayıt Ol":
                email = st.text_input("E-posta Adresi", key="reg_email")
                password = st.text_input("Şifre", type="password", key="reg_pass")
                if st.button("Kayıt Ol", use_container_width=True, type="primary"):
                    register_user(email, password)

            elif secim == "Giriş Yap":
                email = st.text_input("E-posta Adresi", key="login_email")
                password = st.text_input("Şifre", type="password", key="login_pass")
                if st.button("Giriş Yap", use_container_width=True, type="primary"):
                    login_user(email, password)
        
        st.markdown("---")
        st.markdown(f"**AI Modu:** <span style='color: #1E90FF;'>`{st.session_state.api_status}`</span>", unsafe_allow_html=True)
        st.markdown("_Bu mod, kısıtlı ortamlar için özel geliştirilmiştir._")


# =========================================================================
# ANA UYGULAMA AKIŞI
# =========================================================================

def run_app():
    """Uygulamanın ana döngüsüdür."""
    # Sayfa yapılandırması
    st.set_page_config(layout="wide", page_title="AI Arkadaşım", initial_sidebar_state="expanded")
    
    # Custom CSS ekleme (ESTETİK İYİLEŞTİRMELER BURADA!)
    st.markdown("""
        <style>
        /* Genel Arka Plan ve Yazı Tipi */
        body { font-family: 'Inter', sans-serif; }
        
        /* Ana Başlık */
        h1 { 
            color: #1E90FF !important; 
            text-shadow: 1px 1px 2px rgba(0,0,0,0.1);
        }

        /* Streamlit Ana Konteyner Ayarları */
        .stApp {
            background-color: #f7f9fc; 
        }

        /* Buton Stilleri */
        .stButton>button {
            border-radius: 12px !important;
            font-weight: bold;
            color: white !important;
            background-color: #1E90FF !important;
            border: none;
            transition: all 0.3s;
            box-shadow: 0 4px 6px rgba(30, 144, 255, 0.3);
        }
        .stButton>button:hover {
            background-color: #1C86EE !important;
            transform: translateY(-2px);
            box-shadow: 0 6px 10px rgba(30, 144, 255, 0.4);
        }

        /* Input Alanları ve Selectbox'lar */
        .stTextInput>div>div>input, .stSelectbox>div>div {
            border-radius: 8px;
            border: 1px solid #ddd;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }

        /* Mesaj Konteyneri ve Sohbet Baloncukları */
        .stContainer {
            border-radius: 15px;
            box-shadow: 0 8px 16px rgba(0,0,0,0.1);
            background-color: white;
            padding: 20px;
        }

        /* Sidebar Stili */
        .css-vk32hr { /* Streamlit sidebar selector (farklı versiyonlarda değişebilir) */
            background-color: #e9ecef !important;
            border-right: 3px solid #1E90FF;
            border-radius: 0 15px 15px 0;
            box-shadow: 2px 0 5px rgba(0,0,0,0.1);
        }
        </style>
        """, unsafe_allow_html=True)

    
    if not st.session_state.is_loaded:
        display_splash_screen()
        return

    st.markdown("<h1 style='text-align: center;'>🤝 Yapay Zeka Arkadaşın (Multi-Sohbet Sürümü)</h1>", unsafe_allow_html=True)
    
    draw_sidebar()
    
    # Ortadaki ana içerik alanı
    main_content_col = st.columns([1])[0]
    with main_content_col:
        
        # Seçilen sohbet başlığını göster
        current_title = st.session_state.user_threads.get(st.session_state.current_thread_id, "✨ Yeni Sohbet")
        st.markdown(f"## 💬 Mevcut Sohbet: {current_title}")
        
        if st.session_state.user_info or is_trial_active():
            st.info("Bu sürümde birden fazla sohbet kurabilir, sohbete başlayınca başlık otomatik atanır. Sohbet geçmişiniz kaydedilir.", icon="💾")
            draw_chat_interface()
        else:
            st.markdown("## ⚠️ Erişim Kısıtlandı")
            st.warning("Ücretsiz deneme süreniz sona erdi. Sohbeti kullanmaya devam etmek için lütfen soldaki menüden Kayıt Olun veya Giriş Yapın.", icon="🚫")


if __name__ == '__main__':
    run_app()
