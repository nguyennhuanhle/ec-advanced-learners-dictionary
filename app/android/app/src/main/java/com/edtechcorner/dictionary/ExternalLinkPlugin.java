package com.edtechcorner.dictionary;

import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.net.Uri;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * Mở liên kết ngoài bằng app trình duyệt của máy, ở tác vụ riêng (UC-A07).
 * @capacitor/browser mở Chrome Custom Tab nằm ngay trong tác vụ của app: bấm Home rồi mở lại app vẫn thấy thanh Chrome
 * ở trên cùng, người thử tưởng app là trình duyệt (báo 2026-11-05).
 *
 * JS: ExternalLink.open({ url }) — chỉ http/https; reject khi máy không có app nào mở được liên kết.
 */
@CapacitorPlugin(name = "ExternalLink")
public class ExternalLinkPlugin extends Plugin {

    @PluginMethod
    public void open(PluginCall call) {
        String url = call.getString("url");
        Uri uri = url == null ? null : Uri.parse(url);
        if (uri == null || !("http".equals(uri.getScheme()) || "https".equals(uri.getScheme()))) {
            call.reject("not a web link");
            return;
        }
        Intent i = new Intent(Intent.ACTION_VIEW, uri)
            .addCategory(Intent.CATEGORY_BROWSABLE)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            getContext().startActivity(i);
            call.resolve();
        } catch (ActivityNotFoundException e) {
            call.reject("no browser");
        }
    }
}
