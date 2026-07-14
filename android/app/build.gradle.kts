import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

// Release signing credentials are read from local.properties (git-ignored) so
// the keystore password never lands in version control. Keys expected:
//   releaseStoreFile=release-keystore/agents-anywhere-release.jks
//   releaseStorePassword=...
//   releaseKeyAlias=agents-anywhere
//   releaseKeyPassword=...   (same as store password for PKCS12 keystores)
// If any key is missing the release build falls back to unsigned so a fresh
// checkout without the keystore still configures.
val signingProps = Properties().apply {
    val file = rootProject.file("local.properties")
    if (file.exists()) {
        file.inputStream().use { load(it) }
    }
}
val hasReleaseSigning = signingProps.getProperty("releaseStoreFile") != null &&
    rootProject.file(signingProps.getProperty("releaseStoreFile", "")).exists()

android {
    namespace = "com.agentsanywhere.app"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.agentsanywhere.app"
        minSdk = 26
        targetSdk = 36
        versionCode = 6
        versionName = "0.1.7.2"

        vectorDrawables {
            useSupportLibrary = true
        }
    }

    signingConfigs {
        if (hasReleaseSigning) {
            create("release") {
                storeFile = rootProject.file(signingProps.getProperty("releaseStoreFile"))
                storePassword = signingProps.getProperty("releaseStorePassword")
                keyAlias = signingProps.getProperty("releaseKeyAlias")
                // PKCS12 keystores use one password for store and key; fall back
                // to the store password when a separate key password is absent.
                keyPassword = signingProps.getProperty("releaseKeyPassword")
                    ?: signingProps.getProperty("releaseStorePassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            // Only attach the release signingConfig when the keystore is present.
            // A checkout without it still builds (unsigned release) instead of
            // failing configuration.
            if (hasReleaseSigning) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
        isCoreLibraryDesugaringEnabled = true
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
    }
}

dependencies {
    implementation(platform(libs.androidx.compose.bom))
    implementation(platform(libs.sora.bom))
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.camera.camera2)
    implementation(libs.androidx.camera.core)
    implementation(libs.androidx.camera.lifecycle)
    implementation(libs.androidx.camera.mlkit.vision)
    implementation(libs.androidx.camera.view)
    implementation(libs.androidx.compose.animation)
    implementation(libs.androidx.compose.foundation)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.coil.compose)
    implementation(libs.coil.network.okhttp)
    implementation(libs.compose.shimmer)
    implementation(libs.commonmark)
    implementation(libs.commonmark.ext.autolink)
    implementation(libs.commonmark.ext.gfm.strikethrough)
    implementation(libs.commonmark.ext.gfm.tables)
    implementation(libs.commonmark.ext.task.list.items)
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.lucide.icons)
    implementation(libs.mlkit.barcode.scanning)
    implementation(libs.okhttp)
    implementation(libs.sora.editor)
    implementation(libs.sora.language.textmate)
    implementation(libs.sora.oniguruma.native)
    implementation(libs.telephoto.zoomable.image.coil3)
    implementation(libs.termux.terminal.view)
    coreLibraryDesugaring(libs.desugar.jdk.libs)
    testImplementation(libs.junit)
    debugImplementation(libs.androidx.compose.ui.tooling)
}
