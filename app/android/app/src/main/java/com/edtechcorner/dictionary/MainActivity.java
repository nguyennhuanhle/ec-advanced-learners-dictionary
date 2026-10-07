package com.edtechcorner.dictionary;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {

    @Override
    public void onCreate(Bundle savedInstanceState) {
        // plugin riêng của app (không phải gói npm) phải đăng ký trước super.onCreate
        registerPlugin(VoiceCheckPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
