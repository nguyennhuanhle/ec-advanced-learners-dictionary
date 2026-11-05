package com.edtechcorner.dictionary;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;

/**
 * Cửa nhận chữ từ app khác (UC-A08, UC-A12): không có giao diện, chuyển chữ sang MainActivity rồi đóng ngay.
 * Menu chữ gọi startActivityForResult nên nếu nhận thẳng ở MainActivity, Android bỏ qua singleTask và tạo bản thứ hai nằm trong
 * tác vụ của app gọi (đã thấy với Chrome): moveTaskToBack khi đó đẩy luôn Chrome xuống, Back không về được app đang đọc.
 */
public class LookupActivity extends Activity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Intent i = new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        String text = TextIntentPlugin.read(getIntent());
        if (text != null) {
            i.setAction(TextIntentPlugin.ACTION_LOOKUP).putExtra(Intent.EXTRA_TEXT, text);
            if (fromThisApp()) i.putExtra(TextIntentPlugin.EXTRA_SELF, true);
        }
        startActivity(i);
        finish();
    }

    /** Menu chữ ngay trong app này: Back lùi về mục trước như thường, không rời app. */
    private boolean fromThisApp() {
        String me = getPackageName();
        if (me.equals(getCallingPackage())) return true;
        Uri ref = getReferrer();
        return ref != null && me.equals(ref.getHost());
    }
}
