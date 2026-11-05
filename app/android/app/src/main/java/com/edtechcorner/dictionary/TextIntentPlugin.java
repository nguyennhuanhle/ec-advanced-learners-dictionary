package com.edtechcorner.dictionary;

import android.content.Intent;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * Chữ nhận từ app khác (UC-A08 menu chữ PROCESS_TEXT, UC-A12 chia sẻ SEND text/plain), do LookupActivity chuyển tới.
 * App chỉ đọc chữ, không trả chữ về.
 *
 * JS: TextIntent.take() → { text?, self? } chữ chờ từ lúc khởi động nguội, lấy xong thì xoá.
 *     Sự kiện "text" { text, self }: chữ mới khi app đang chạy (launchMode singleTask → onNewIntent).
 *     self = chữ được chọn ngay trong app này.
 */
@CapacitorPlugin(name = "TextIntent")
public class TextIntentPlugin extends Plugin {

    static final String ACTION_LOOKUP = "com.edtechcorner.dictionary.LOOKUP";
    static final String EXTRA_SELF = "com.edtechcorner.dictionary.SELF";

    /** Giới hạn của use case: dòng đầu, tối đa 100 ký tự. Giao diện còn rút gọn tiếp như khi tự gõ. */
    private static final int MAX_CHARS = 100;

    private JSObject pending;

    @Override
    public void load() {
        Intent i = getActivity().getIntent();
        // mở lại từ màn hình Gần đây dùng lại intent cũ: không tra lại
        if (i != null && (i.getFlags() & Intent.FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY) == 0) pending = received(i);
    }

    @PluginMethod
    public void take(PluginCall call) {
        call.resolve(pending != null ? pending : new JSObject());
        pending = null;
    }

    @Override
    protected void handleOnNewIntent(Intent intent) {
        JSObject data = received(intent);
        if (data == null) return;
        if (hasListeners("text")) notifyListeners("text", data);
        else pending = data;
    }

    private static JSObject received(Intent i) {
        if (!ACTION_LOOKUP.equals(i.getAction())) return null;
        String text = i.getStringExtra(Intent.EXTRA_TEXT);
        if (text == null) return null;
        JSObject data = new JSObject();
        data.put("text", text);
        data.put("self", i.getBooleanExtra(EXTRA_SELF, false));
        return data;
    }

    /** Chữ trong intent từ app khác, đã rút gọn; null nếu không có chữ dùng được. */
    static String read(Intent i) {
        CharSequence cs = null;
        try {
            if (Intent.ACTION_PROCESS_TEXT.equals(i.getAction())) cs = i.getCharSequenceExtra(Intent.EXTRA_PROCESS_TEXT);
            else if (Intent.ACTION_SEND.equals(i.getAction())) cs = i.getCharSequenceExtra(Intent.EXTRA_TEXT);
        } catch (RuntimeException e) {
            return null; // extra hỏng do app gửi: coi như không có chữ
        }
        if (cs == null) return null;
        String s = cs.toString().trim();
        int nl = s.indexOf('\n');
        if (nl >= 0) s = s.substring(0, nl).trim();
        if (s.isEmpty()) return null;
        if (s.codePointCount(0, s.length()) > MAX_CHARS) s = s.substring(0, s.offsetByCodePoints(0, MAX_CHARS));
        return s;
    }
}
