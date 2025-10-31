import gradio as gr
import time
import requests
import json
from functools import wraps

# =============================================================================
# 1. KONFİGÜRASYON VE BAŞLANGIÇ AYARLARI
# =============================================================================

# KULLANICI TARAFINDAN SAĞLANAN API ANAHTARI
# Bu alandaki anahtar, sizin en son sağladığınız anahtardır.
GEMINI_API_KEY = "AIzaSyBmtvU_ceKdSXf-jVmrUPYeH1L9pDw5vdc"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent"

SYSTEM_INSTRUCTION = """
Sen, kullanıcının web sitesindeki resmi AI asistanısın. Görevin, her zaman arkadaş canlısı, samimi ve doğal bir tonda yanıt vermek. 
Robotik dilden kaçın ve sanki bir dostunmuş gibi konuş.
Kullanıcının sorduğu detaylı sorulara (tarih, bilim, güncel olaylar vb.) cevap vermek için her zaman Google'da arama yapma yeteneğini kullan. 
Yanıtlarını daima Türkçe ver ve Türk kültürüne uygun, sıcak ifadeler kullan.
"""

TRIAL_DURATION = 120 # Deneme süresi (saniye)
INITIAL_MESSAGE = [(None, "Selamlar! Ben senin AI arkadaşınım. Nasılsın bakalım? Aklına takılan her şeyi bana sorabilirsin.")]

# =============================================================================
# 2. YARDIMCI FONKSİYONLAR
# =============================================================================

def format_sources(grounding_attributions):
    """API'den gelen kaynakları okunabilir Markdown formatına dönüştürür."""
    if not grounding_attributions:
        return ""

    source_list = "\n\n**Kaynaklar:**\n"
    for i, attr in enumerate(grounding_attributions):
        uri = attr.get('web', {}).get('uri')
        title = attr.get('web', {}).get('title', "Bilinmeyen Başlık")
        if uri:
            # Markdown link olarak formatla
            source_list += f"{i + 1}. [{title}]({uri})\n"
    return source_list

def is_trial_active(start_time, is_logged_in):
    """Deneme süresinin aktif olup olmadığını kontrol eder."""
    if is_logged_in:
        return True # Giriş yapılmışsa her zaman aktif
    
    elapsed_time = time.time() - start_time
    return elapsed_time < TRIAL_DURATION

# =============================================================================
# 3. GRADIO KULLANICI ARAYÜZÜ İŞLEVLERİ (AUTH SİMÜLASYONU)
# =============================================================================

def login_user(email, password, is_login, state):
    """Basitleştirilmiş kullanıcı giriş/kayıt simülasyonu."""
    
    if not email or len(password) < 6:
        return "E-posta veya şifre geçersiz. Lütfen geçerli bilgiler girin.", state
    
    # Giriş Başarılı Simülasyonu
    new_state = state.copy()
    new_state['logged_in'] = True
    new_state['user_email'] = email
    
    if is_login:
        return f"Giriş başarılı! Hoş geldin, {email}. Artık süresiz sohbet edebilirsin.", new_state
    else: # Kayıt
        return f"Kayıt başarılı! Hoş geldin, {email}. Artık süresiz sohbet edebilirsin.", new_state

def logout_user(state):
    """Kullanıcı çıkışı yapar ve durumu sıfırlar."""
    new_state = {
        'logged_in': False,
        'user_email': None,
        'start_time': time.time(), # Deneme süresini sıfırla
    }
    # Sohbet geçmişi temizlenir
    return "Başarıyla çıkış yaptınız. Deneme modu yeniden başladı (120 saniye).", INITIAL_MESSAGE, new_state

def reset_chat(state):
    """Sohbet geçmişini ve deneme süresini sıfırlar."""
    new_state = state.copy()
    if not new_state.get('logged_in', False):
         new_state['start_time'] = time.time() # Deneme süresini sıfırla
         return "Sohbet geçmişi temizlendi. Deneme süresi yeniden başlatıldı (120 saniye).", INITIAL_MESSAGE, new_state
    
    return "Sohbet geçmişi temizlendi.", INITIAL_MESSAGE, new_state
    
# =============================================================================
# 4. GEMINI API VE SOHBET MANTIĞI
# =============================================================================

def predict(message, history, state):
    """Kullanıcı mesajını alır, API'ye gönderir ve yanıtı döndürür (Gemini API ile)."""
    
    # Oturum Durumu Kontrolü
    is_logged_in = state.get('logged_in', False)
    start_time = state.get('start_time', time.time())
    
    if not is_trial_active(start_time, is_logged_in):
        yield "❌ Üzgünüm, deneme süreniz sona erdi. Sohbeti devam ettirmek için lütfen sol panelden giriş yapın veya kayıt olun."
        return

    if not GEMINI_API_KEY:
        yield "❌ API Anahtarı eksik. Lütfen `app.py` dosyasını kontrol edin."
        return
        
    # Geçmişi API formatına dönüştür (Gradio formatı [[kullanıcı, model], ...] içerir)
    contents_for_api = []
    for user_msg, model_msg in history:
        # Önceki kullanıcı mesajı
        if user_msg:
            contents_for_api.append({"role": "user", "parts": [{"text": user_msg}]})
        # Önceki model mesajı
        if model_msg:
            # Kaynakları temizle
            clean_model_msg = model_msg.split("**Kaynaklar:**")[0].strip() 
            contents_for_api.append({"role": "model", "parts": [{"text": clean_model_msg}]})

    # Yeni mesajı ekle
    contents_for_api.append({"role": "user", "parts": [{"text": message}]})

    payload = {
        "contents": contents_for_api, 
        "tools": [{"google_search": {}}], 
        "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]}
    }

    url = f"{GEMINI_API_URL}?key={GEMINI_API_KEY}"
    
    yield "🤖 Düşünüyorum... (Google'da arama yapıyor olabilirim)"
    
    try:
        response = requests.post(url, headers={'Content-Type': 'application/json'}, json=payload, timeout=30)
        
        if not response.ok:
            error_details = response.json().get('error', {}).get('message', 'Bilinmeyen Hata')
            yield f"❌ API Bağlantı Hatası ({response.status_code}): {error_details}. Anahtarınızı kontrol edin."
            return

        result = response.json()
        
        candidate = result.get('candidates', [{}])[0]
        text = candidate.get('content', {}).get('parts', [{}])[0].get('text', 'Üzgünüm, yanıt oluşturulamadı. (Boş Geri Dönüş)')
        
        # Kaynakları formatla ve ekle
        sources = format_sources(candidate.get('groundingMetadata', {}).get('groundingAttributions'))
        
        final_response = text + sources
        
        yield final_response

    except requests.exceptions.Timeout:
        yield "⏳ API zaman aşımına uğradı (30 saniye). Lütfen tekrar deneyin veya daha kısa bir soru sorun."
    except Exception as e:
        yield f"❌ Dış dünyadan bilgi çekerken bir sorun çıktı: {type(e).__name__} - {e}"

# =============================================================================
# 5. GRADIO ARAYÜZ TANIMI (UI)
# =============================================================================

default_state = {
    'logged_in': False,
    'user_email': None,
    'start_time': time.time(),
}

with gr.Blocks(title="Gradio AI Sohbet Sistemi", theme=gr.themes.Soft()) as demo:
    state = gr.State(value=default_state)
    
    gr.Markdown(
    """
    <div style="text-align: center; padding: 20px; background-color: #5b21b6; color: white; border-radius: 10px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);">
        <h1 style="font-size: 2em; font-weight: bold;">Gradio AI Sohbet Arkadaşın</h1>
        <p>Python ile Gradio üzerinde çalışan, Streamlit hatalarından arındırılmış, güvenilir arayüz.</p>
    </div>
    """
    )
    
    with gr.Row(variant="panel"):
        
        # 1. Sol Kolon: Auth ve Süre Bilgisi
        with gr.Column(scale=1, min_width=300):
            
            gr.Markdown("## 🔒 Oturum Yönetimi (Simülasyon)")
            
            with gr.Row():
                auth_email = gr.Textbox(label="E-posta", placeholder="kullanici@example.com", lines=1)
                auth_password = gr.Textbox(label="Şifre", type="password", placeholder="Şifre (min 6)", lines=1)
            
            with gr.Row():
                login_btn = gr.Button("Giriş Yap", variant="primary")
                register_btn = gr.Button("Kayıt Ol", variant="secondary")

            logout_btn = gr.Button("Çıkış Yap", variant="stop")
            auth_output = gr.Markdown("Oturum Durumu: Giriş Yapılmadı.")

            # Auth Fonksiyon Bağlantıları
            login_btn.click(
                fn=lambda e, p, s: login_user(e, p, True, s), 
                inputs=[auth_email, auth_password, state], 
                outputs=[auth_output, state]
            )
            register_btn.click(
                fn=lambda e, p, s: login_user(e, p, False, s), 
                inputs=[auth_email, auth_password, state], 
                outputs=[auth_output, state]
            )
            logout_btn.click(
                fn=logout_user, 
                inputs=[state], 
                outputs=[auth_output, "chatbot", state] 
            )
            
            gr.Markdown("---")
            
            # Deneme Süresi Durumu Görüntüleyici
            def update_time_display(state):
                """Zamanlayıcıyı her saniye günceller."""
                is_logged_in = state.get('logged_in', False)
                start_time = state.get('start_time', time.time())
                
                if is_logged_in:
                    return "Süresiz Erişim (Giriş Yapıldı)", "#10b981" 
                
                remaining = max(0, TRIAL_DURATION - int(time.time() - start_time))
                
                if remaining == 0:
                    return "Süre Bitti! Lütfen giriş yapın.", "#ef4444"
                elif remaining < 30:
                    return f"Deneme Süresi: {remaining} sn kaldı!", "#f59e0b"
                else:
                    return f"Deneme Süresi: {remaining} sn kaldı", "#3b82f6"

            def update_ui_colors(time_text, color):
                """Metin ve renge göre HTML ile bir kutu döndürür."""
                return f"""
                <div style="background-color: {color}; color: white; padding: 10px; border-radius: 5px; text-align: center; font-weight: bold;">
                    {time_text}
                </div>
                """

            time_text_output = gr.Text(visible=False) 
            time_color_output = gr.Text(visible=False) 
            time_display_html = gr.HTML(update_ui_colors(*update_time_display(default_state)))
            
            # Her saniye UI'ı güncelle
            demo.load(
                fn=update_time_display, 
                inputs=[state], 
                outputs=[time_text_output, time_color_output], 
                every=1
            ).then(
                fn=update_ui_colors, 
                inputs=[time_text_output, time_color_output], 
                outputs=[time_display_html]
            )


        # 2. Sağ Kolon: Sohbet Arayüzü
        with gr.Column(scale=3):
            gr.Markdown("## 💬 AI ile Sohbet Et")
            
            chat_interface = gr.ChatInterface(
                fn=predict, 
                chatbot=gr.Chatbot(height=500, label="AI Sohbeti", elem_id="chatbot", 
                                   value=INITIAL_MESSAGE if not default_state['logged_in'] else []),
                textbox=gr.Textbox(placeholder="Mesajınızı buraya yazın...", container=False, scale=7),
                theme="soft",
                submit_btn="Gönder",
                retry_btn=None,
                undo_btn=None,
                clear_btn="Sohbeti Temizle (Denemeyi Sıfırla)"
            ).queue() 
            
            # Clear butonunu reset_chat fonksiyonuna bağla
            chat_interface.clear_btn.click(
                fn=reset_chat,
                inputs=[state],
                outputs=[auth_output, chat_interface.chatbot, state]
            )
            
            # Predict fonksiyonunun state'i almasını sağla
            chat_interface.fn_kwargs['state'] = state 

# Gradio uygulamasını başlat
if __name__ == "__main__":
    # share=False, uygulamayı sadece yerel makinenizde veya sunucuda çalıştırır.
    demo.launch(share=False)
