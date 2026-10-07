package com.edtechcorner.dictionary;

import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.speech.tts.TextToSpeech;
import android.speech.tts.Voice;
import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.TreeSet;

/**
 * Giọng đọc nào ĐÃ CÀI trên máy (UC-A03). Plugin text-to-speech chỉ hỏi isLanguageAvailable(), mà Speech Services by Google
 * trả "có" cả khi dữ liệu giọng chưa tải (rồi đọc bằng giọng khác: bấm loa UK nghe giọng Mỹ, chữ Việt đọc bằng giọng Anh).
 * Ở đây đọc Voice.getFeatures(): giọng có KEY_FEATURE_NOT_INSTALLED là chưa tải.
 *
 * JS: VoiceCheck.installed() → { engine, langs: string[] (vd. ["en-US", "vi-VN"]), voices: [{ name, lang, network }] }
 *     (chỉ giọng đã cài). Phải chọn ĐÍCH DANH giọng: chỉ đặt ngôn ngữ en-GB thì Google TTS vẫn có thể đọc giọng Mỹ
 *     (đã thấy trên Galaxy S22 Ultra: "en-GB-language" → en-us-x-iog; chọn "en-gb-x-gbb-local" → giọng Anh).
 *     VoiceCheck.openInstall() → mở màn hình tải giọng của engine mặc định (INSTALL_TTS_DATA); không được thì
 *     Cài đặt › Chuyển văn bản thành giọng nói. (openInstall của plugin TTS chỉ gọi CHECK_TTS_DATA — chạy ngầm, không có giao diện.)
 */
@CapacitorPlugin(name = "VoiceCheck")
public class VoiceCheckPlugin extends Plugin {

    private TextToSpeech tts;
    /** 0 = đang khởi tạo, 1 = sẵn sàng, -1 = máy không có engine TextToSpeech */
    private int state = 0;
    private final List<PluginCall> waiting = new ArrayList<>();

    @Override
    public void load() {
        tts = new TextToSpeech(getContext(), (status) -> {
            synchronized (waiting) {
                state = status == TextToSpeech.SUCCESS ? 1 : -1;
                for (PluginCall c : waiting) answer(c);
                waiting.clear();
            }
        });
    }

    @PluginMethod
    public void installed(PluginCall call) {
        synchronized (waiting) {
            if (state == 0) {
                waiting.add(call);
                return;
            }
        }
        answer(call);
    }

    private void answer(PluginCall call) {
        JSObject ret = new JSObject();
        Set<String> langs = new TreeSet<>();
        JSArray list = new JSArray();
        boolean engine = state == 1;
        if (engine) {
            try {
                Set<Voice> voices = tts.getVoices();
                if (voices != null) {
                    for (Voice v : voices) {
                        Set<String> f = v.getFeatures();
                        if (f != null && f.contains(TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED)) continue;
                        langs.add(v.getLocale().toLanguageTag());
                        JSObject o = new JSObject();
                        o.put("name", v.getName());
                        o.put("lang", v.getLocale().toLanguageTag());
                        o.put("network", v.isNetworkConnectionRequired());
                        list.put(o);
                    }
                }
            } catch (Exception e) {
                engine = false;
            }
        }
        ret.put("engine", engine);
        ret.put("langs", JSArray.from(langs.toArray()));
        ret.put("voices", list);
        call.resolve(ret);
    }

    @PluginMethod
    public void openInstall(PluginCall call) {
        Intent i = new Intent(TextToSpeech.Engine.ACTION_INSTALL_TTS_DATA);
        if (tts != null && tts.getDefaultEngine() != null) i.setPackage(tts.getDefaultEngine());
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            getContext().startActivity(i);
            call.resolve();
            return;
        } catch (ActivityNotFoundException e) {
            // engine không có màn hình tải giọng → mở cài đặt TTS của hệ thống
        }
        try {
            Intent s = new Intent("com.android.settings.TTS_SETTINGS");
            s.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(s);
            call.resolve();
        } catch (ActivityNotFoundException e) {
            call.reject("no voice settings screen");
        }
    }

    @Override
    protected void handleOnDestroy() {
        if (tts != null) tts.shutdown();
    }
}
