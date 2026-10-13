package com.luciesinreglas.recibir

import android.app.Activity
import android.os.Bundle
import android.os.Build
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.content.ClipboardManager
import android.content.ClipData
import android.content.Context
import android.view.View
import android.view.WindowInsets
import android.view.WindowManager
import android.widget.*
import java.net.NetworkInterface
import java.net.Inet4Address
import java.security.SecureRandom

class MainActivity : Activity() {
    private lateinit var receiver: ReceiverServer
    private lateinit var content: LinearLayout
    private lateinit var status: TextView
    private lateinit var address: TextView
    private lateinit var identity: TextView
    private lateinit var pending: LinearLayout
    private lateinit var history: LinearLayout
    private lateinit var pinLabel: TextView
    private val cyan=Color.rgb(0,228,238)
    private val white=Color.rgb(238,244,252)
    private val muted=Color.rgb(166,183,204)
    private lateinit var toggle: Button
    private lateinit var cancelButton: Button
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val scroll=ScrollView(this).apply{setBackgroundColor(Color.rgb(5,8,17));isFillViewport=true}
        content=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(dp(22),dp(24),dp(22),dp(24))}
        scroll.addView(content)
        setContentView(scroll)
        scroll.setOnApplyWindowInsetsListener { v,insets ->
            if(Build.VERSION.SDK_INT>=30){val bars=insets.getInsets(WindowInsets.Type.systemBars());v.setPadding(0,bars.top,0,bars.bottom)}
            else{v.setPadding(0,insets.systemWindowInsetTop,0,insets.systemWindowInsetBottom)}
            insets
        }
        text("LUCIE / SIN REGLAS",12,cyan,true).apply { letterSpacing=0.16f }
        text("Recibir archivos",32,white,true).apply { typeface=Typeface.create("sans-serif-condensed",Typeface.BOLD) }
        text("Del estudio a tu celular. Abrí el dashboard y elegí qué enviar.",15,muted)
        val connection=card()
        connection.addView(label("CONEXIÓN WI-FI",11,cyan,true).apply { letterSpacing=0.12f })
        address=label("Preparando conexión…",23,white,true)
        connection.addView(address)
        connection.addView(label("Puerto ${ReceiverServer.RECEIVE_PORT} · conexión segura",12,muted))
        status=label("Iniciando receptor seguro…",14,cyan,true)
        status.accessibilityLiveRegion=View.ACCESSIBILITY_LIVE_REGION_POLITE
        connection.addView(status)
        connection.addView(action("Copiar IP") {
            val clip=getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            clip.setPrimaryClip(ClipData.newPlainText("Lucie Recibir",localAddresses().firstOrNull() ?: ""))
            Toast.makeText(this,"Dirección copiada",Toast.LENGTH_SHORT).show()
        })
        identity=label("Identidad HTTPS: preparando…",11,muted).apply {
            typeface=Typeface.MONOSPACE;setTextIsSelectable(true);visibility=View.GONE
        }
        connection.addView(secondary("Ver identidad segura") {
            identity.visibility=if(identity.visibility==View.VISIBLE)View.GONE else View.VISIBLE
        })
        connection.addView(identity)
        text("Próximo envío",21,white,true)
        pending=card()
        val security=card()
        val pinCheck=CheckBox(this).apply {
            text="Exigir PIN además de aceptar";setTextColor(white);textSize=14f
            buttonTintList=android.content.res.ColorStateList.valueOf(cyan)
        }
        security.addView(pinCheck)
        pinLabel=label("",17,cyan,true).apply { visibility=View.GONE }
        security.addView(pinLabel)
        cancelButton=secondary("Cancelar recepción actual") {receiver.cancelLocal();update()}
        content.addView(cancelButton,LinearLayout.LayoutParams(-1,-2).apply{topMargin=dp(10)})
        toggle=secondary("Detener / activar receptor") {
            if(receiver.listening){receiver.stop();status.text="Receptor detenido."}else{status.text="Iniciando…";receiver.start()}
            update()
        }
        content.addView(toggle,LinearLayout.LayoutParams(-1,-2).apply{topMargin=dp(4)})
        text("Tu historial",21,white,true)
        text("Videos en Movies, fotos en Pictures y MP3 en Music / LucieSinReglas.",13,muted)
        history=card()
        receiver=ReceiverServer(applicationContext){message->runOnUiThread{status.text=message;update()}}
        pinCheck.setOnCheckedChangeListener{_,checked->
            receiver.pin=if(checked)(1000+SecureRandom().nextInt(9000)).toString() else null
            pinLabel.text=if(checked)"PIN: ${receiver.pin}" else ""
            pinLabel.visibility=if(checked)View.VISIBLE else View.GONE
        }
        update()
    }
    override fun onResume(){super.onResume();receiver.start()}
    override fun onStop(){receiver.stop();super.onStop()}
    private fun update() {
        address.text=localAddresses().joinToString("\n").ifBlank{"Conectate a Wi-Fi para recibir"}
        if(receiver.fingerprint.isNotEmpty()){
            identity.text="Huella HTTPS · comparala en el dashboard:\n${receiver.fingerprint}"
        }
        pending.removeAllViews()
        val session=receiver.state.session
        cancelButton.isEnabled=session!=null
        if(session==null){
            pending.addView(label("Esperando tu selección",17,white,true))
            pending.addView(label("En el dashboard, abrí Sin publicar y tocá Buscar celulares. Mantené esta pantalla abierta en la misma Wi-Fi.",14,muted))
        }
        else{
            pending.addView(label("De: ${session.sender}",17,white,true))
            session.files.forEach{f->pending.addView(label("${f.name}\n${f.size/1024} KB · ${if(f.sha256!=null)"Verificación SHA-256" else "Sin hash del emisor"}",14,muted))}
            if(!session.accepted){
                pending.addView(action("Aceptar archivos"){receiver.decide(true);update()})
                pending.addView(secondary("Rechazar"){receiver.decide(false);update()})
            }
        }
        history.removeAllViews()
        receiver.sink.history().ifEmpty{listOf("Tus recepciones aparecerán acá.")}.forEach{history.addView(label(it,14,muted))}
    }
    private fun localAddresses():List<String> = runCatching {
        val manager = getSystemService(Context.CONNECTIVITY_SERVICE) as android.net.ConnectivityManager
        val network = manager.activeNetwork
        val wifi = manager.getNetworkCapabilities(network)?.hasTransport(android.net.NetworkCapabilities.TRANSPORT_WIFI) == true
        if (wifi) {
            val ips = manager.getLinkProperties(network)?.linkAddresses?.map { it.address }?.filterIsInstance<Inet4Address>()?.mapNotNull { it.hostAddress } ?: emptyList()
            if (ips.isNotEmpty()) return ips
        }
        NetworkInterface.getNetworkInterfaces().toList().flatMap{it.inetAddresses.toList()}
            .filter{it is Inet4Address && !it.isLoopbackAddress && it.isSiteLocalAddress}.mapNotNull{it.hostAddress}
    }.getOrDefault(emptyList())
    private fun dp(value:Int)=(value*resources.displayMetrics.density).toInt()
    private fun background()=GradientDrawable().apply{setColor(Color.rgb(12,20,35));cornerRadius=dp(18).toFloat();setStroke(dp(1),Color.rgb(41,58,80))}
    private fun card()=LinearLayout(this).apply{
        orientation=LinearLayout.VERTICAL;background=background();setPadding(dp(18),dp(14),dp(18),dp(14))
        content.addView(this,LinearLayout.LayoutParams(-1,-2).apply{topMargin=dp(12);bottomMargin=dp(8)})
    }
    private fun label(value:String,size:Int,color:Int,bold:Boolean=false)=TextView(this).apply{
        text=value;textSize=size.toFloat();setTextColor(color);setPadding(0,dp(8),0,dp(8));if(bold)setTypeface(typeface,Typeface.BOLD)
    }
    private fun text(value:String,size:Int,color:Int,bold:Boolean=false)=label(value,size,color,bold).also{content.addView(it)}
    private fun action(value:String,clicked:()->Unit)=Button(this).apply{
        text=value;isAllCaps=false;setTextColor(Color.rgb(5,8,17));backgroundTintList=android.content.res.ColorStateList.valueOf(cyan)
        setOnClickListener{clicked()};minHeight=dp(48);textSize=14f
        background=GradientDrawable().apply{setColor(cyan);cornerRadius=dp(12).toFloat()}
    }
    private fun secondary(value:String,clicked:()->Unit)=action(value,clicked).apply{
        setTextColor(white);backgroundTintList=null
        background=GradientDrawable().apply{setColor(Color.rgb(16,27,44));cornerRadius=dp(12).toFloat();setStroke(dp(1),Color.rgb(41,58,80))}
    }
    private fun button(value:String,clicked:()->Unit){content.addView(action(value,clicked),LinearLayout.LayoutParams(-1,-2).apply{topMargin=dp(6)})}
}
