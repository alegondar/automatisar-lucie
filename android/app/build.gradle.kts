plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
android {
    namespace = "com.luciesinreglas.recibir"
    compileSdk = 35
    defaultConfig {
        applicationId = "com.luciesinreglas.recibir"
        minSdk = 29
        targetSdk = 35
        versionCode = 2
        versionName = "0.2.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
}
dependencies {
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
}
