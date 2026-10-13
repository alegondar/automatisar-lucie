package com.luciesinreglas.recibir

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.math.BigInteger
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.MessageDigest
import java.security.PrivateKey
import java.security.Principal
import java.net.Socket
import java.util.Date
import javax.net.ssl.SSLContext
import javax.net.ssl.X509ExtendedKeyManager
import javax.security.auth.x500.X500Principal
import java.security.cert.X509Certificate

class Identity {
    private val alias = "lucie-recibir-tls-ec-v2"
    private val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    init {
        if (!store.containsAlias(alias)) {
            val generator = KeyPairGenerator.getInstance("EC", "AndroidKeyStore")
            generator.initialize(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY)
                .setAlgorithmParameterSpec(java.security.spec.ECGenParameterSpec("secp256r1"))
                .setDigests(KeyProperties.DIGEST_NONE, KeyProperties.DIGEST_SHA256, KeyProperties.DIGEST_SHA512)
                .setCertificateSubject(X500Principal("CN=Lucie Recibir"))
                .setCertificateSerialNumber(BigInteger.ONE)
                .setCertificateNotBefore(Date(System.currentTimeMillis() - 86_400_000L))
                .setCertificateNotAfter(Date(System.currentTimeMillis() + 315_360_000_000L)).build())
            generator.generateKeyPair()
        }
    }
    private val certificate get() = store.getCertificate(alias) as X509Certificate
    val fingerprint get() = MessageDigest.getInstance("SHA-256").digest(certificate.encoded).joinToString("") { "%02x".format(it) }
    fun context(): SSLContext {
        val manager = object : X509ExtendedKeyManager() {
            override fun getClientAliases(keyType: String?, issuers: Array<out Principal>?): Array<String>? = null
            override fun chooseClientAlias(keyType: Array<out String>?, issuers: Array<out Principal>?, socket: Socket?): String? = null
            override fun getServerAliases(keyType: String?, issuers: Array<out Principal>?): Array<String>? = if (keyType == "EC") arrayOf(alias) else null
            override fun chooseServerAlias(keyType: String?, issuers: Array<out Principal>?, socket: Socket?): String? = if (keyType == "EC") alias else null
            override fun getCertificateChain(alias: String?): Array<X509Certificate> = arrayOf(certificate)
            override fun getPrivateKey(alias: String?): PrivateKey = store.getKey(this@Identity.alias, null) as PrivateKey
        }
        return SSLContext.getInstance("TLS").apply { init(arrayOf(manager), null, null) }
    }
}
