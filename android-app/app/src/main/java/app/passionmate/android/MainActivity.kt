package app.passionmate.android

import android.app.DownloadManager
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.res.Configuration
import android.net.ConnectivityManager
import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.os.Message
import android.os.SystemClock
import android.util.Log
import android.view.View
import android.widget.Toast
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceError
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.ProgressBar
import androidx.activity.addCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity

private const val TAG = "PassionMateApp"
private const val START_URL = "https://passionmate.app/"
private val ALLOWED_HOSTS = setOf("passionmate.app", "www.passionmate.app")
private const val EXIT_CONFIRM_WINDOW_MS = 2000L
private const val MAX_TEXT_ZOOM_SCALE = 1.3f

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var loadingSpinner: ProgressBar
    private lateinit var retryContainer: View

    private var filePathCallback: ValueCallback<Array<Uri>>? = null
    private var lastBackPressedAt = 0L

    private val fileChooserLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            Log.d(TAG, "[FILE_CHOOSER] result resultCode=${result.resultCode}")
            val results = if (result.resultCode == RESULT_OK) {
                WebChromeClient.FileChooserParams.parseResult(result.resultCode, result.data)
            } else {
                null
            }
            Log.d(TAG, "[FILE_CHOOSER] resolved uris=${results?.size ?: 0}")
            filePathCallback?.onReceiveValue(results)
            filePathCallback = null
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Log.d(TAG, "[ON_CREATE] starting, debuggable=${BuildConfig.WEBVIEW_DEBUGGABLE}")
        setContentView(R.layout.activity_main)

        webView = findViewById(R.id.webview)
        loadingSpinner = findViewById(R.id.loading_spinner)
        retryContainer = findViewById(R.id.retry_container)

        findViewById<View>(R.id.retry_button).setOnClickListener {
            Log.d(TAG, "[RETRY_BUTTON] tapped")
            attemptLoad()
        }

        configureWebView()
        attemptLoad()

        onBackPressedDispatcher.addCallback(this) {
            val canGoBack = webView.canGoBack()
            Log.d(TAG, "[BACK_PRESSED] canGoBack=$canGoBack")
            if (canGoBack) {
                webView.goBack()
                return@addCallback
            }
            // The web app switches screens by toggling display rather than pushing history,
            // so canGoBack() is false even deep inside the app and a single back press would
            // quit outright - too easy to do by accident mid-practice. Require a confirming
            // second press within EXIT_CONFIRM_WINDOW_MS.
            val now = SystemClock.elapsedRealtime()
            if (now - lastBackPressedAt < EXIT_CONFIRM_WINDOW_MS) {
                Log.d(TAG, "[BACK_PRESSED] confirmed - exiting")
                remove()
                onBackPressedDispatcher.onBackPressed()
            } else {
                Log.d(TAG, "[BACK_PRESSED] first press - asking for confirmation")
                lastBackPressedAt = now
                Toast.makeText(this@MainActivity, R.string.back_to_exit, Toast.LENGTH_SHORT).show()
            }
        }
    }

    // configChanges now keeps this Activity alive across font-size/theme changes, so nothing
    // re-runs configureWebView() - textZoom has to be refreshed here or the new size only takes
    // effect after a manual restart.
    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        Log.d(TAG, "[CONFIG_CHANGED] fontScale=${newConfig.fontScale}")
        applyTextZoom(webView.settings)
    }

    private fun configureWebView() {
        Log.d(TAG, "[CONFIGURE_WEBVIEW] applying settings")
        val settings: WebSettings = webView.settings
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.mediaPlaybackRequiresUserGesture = false
        settings.setSupportMultipleWindows(true) // required for onCreateWindow to fire on target="_blank"
        applyTextZoom(settings)

        WebView.setWebContentsDebuggingEnabled(BuildConfig.WEBVIEW_DEBUGGABLE)

        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                // Single-domain app - everything on our own host loads inline in the WebView.
                val intercept = request.url.host !in ALLOWED_HOSTS
                Log.d(TAG, "[SHOULD_OVERRIDE_URL] host=${request.url.host} intercept=$intercept")
                // Blocking the load without opening it anywhere made external links look dead -
                // nothing happened at all when tapped. Hand them to the system browser instead.
                if (intercept) {
                    try {
                        startActivity(Intent(Intent.ACTION_VIEW, request.url))
                    } catch (e: ActivityNotFoundException) {
                        Log.w(TAG, "[SHOULD_OVERRIDE_URL] no app can open ${request.url}", e)
                    }
                }
                return intercept
            }

            override fun onPageStarted(view: WebView, url: String?, favicon: android.graphics.Bitmap?) {
                Log.d(TAG, "[PAGE_STARTED] url=$url")
                loadingSpinner.visibility = View.VISIBLE
            }

            override fun onPageFinished(view: WebView, url: String?) {
                Log.d(TAG, "[PAGE_FINISHED] url=$url")
                loadingSpinner.visibility = View.GONE
            }

            override fun onReceivedError(
                view: WebView,
                request: WebResourceRequest,
                error: WebResourceError
            ) {
                Log.w(
                    TAG,
                    "[PAGE_ERROR] mainFrame=${request.isForMainFrame} url=${request.url} " +
                        "errorCode=${error.errorCode} description=${error.description}"
                )
                if (request.isForMainFrame) {
                    showRetryScreen()
                }
            }

            override fun onReceivedHttpError(
                view: WebView,
                request: WebResourceRequest,
                errorResponse: android.webkit.WebResourceResponse
            ) {
                Log.w(
                    TAG,
                    "[HTTP_ERROR] mainFrame=${request.isForMainFrame} url=${request.url} " +
                        "status=${errorResponse.statusCode}"
                )
                // 4xx on the main frame used to fall through to Chromium's own error page,
                // which looks nothing like the app. Treat any main-frame failure the same way.
                if (request.isForMainFrame && errorResponse.statusCode >= 400) {
                    showRetryScreen()
                }
            }
        }

        webView.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                webView: WebView,
                callback: ValueCallback<Array<Uri>>,
                params: FileChooserParams
            ): Boolean {
                Log.d(TAG, "[FILE_CHOOSER] triggered, acceptTypes=${params.acceptTypes.joinToString()}")
                filePathCallback = callback
                return try {
                    fileChooserLauncher.launch(params.createIntent())
                    true
                } catch (e: Exception) {
                    Log.e(TAG, "[FILE_CHOOSER] failed to launch picker", e)
                    filePathCallback = null
                    false
                }
            }

            // target="_blank" links (e.g. homework/curriculum attachment downloads) never reach
            // shouldOverrideUrlLoading or setDownloadListener - Chromium WebView treats them as a
            // popup-window request, which is silently dropped unless onCreateWindow is handled.
            // We don't want real popups (this is a single-domain app), so capture the target URL
            // via a throwaway WebView and hand it straight to the same download path.
            override fun onCreateWindow(
                view: WebView,
                isDialog: Boolean,
                isUserGesture: Boolean,
                resultMsg: Message
            ): Boolean {
                Log.d(TAG, "[CREATE_WINDOW] intercepting popup request")
                val popupCatcher = WebView(this@MainActivity)
                popupCatcher.webViewClient = object : WebViewClient() {
                    override fun shouldOverrideUrlLoading(v: WebView, request: WebResourceRequest): Boolean {
                        Log.d(TAG, "[CREATE_WINDOW] captured popup target url=${request.url}")
                        startDownload(request.url.toString(), null, null)
                        return true
                    }
                }
                val transport = resultMsg.obj as WebView.WebViewTransport
                transport.webView = popupCatcher
                resultMsg.sendToTarget()
                return true
            }
        }

        webView.setDownloadListener { url, _, contentDisposition, mimeType, contentLength ->
            Log.d(
                TAG,
                "[DOWNLOAD_LISTENER] url=$url mimeType=$mimeType contentLength=$contentLength"
            )
            startDownload(url, contentDisposition, mimeType)
        }
    }

    /**
     * WebView ignores the system font scale unless textZoom is set explicitly, so raising the
     * phone's font size did nothing to this app at all (verified on 2026-09-20 at 1.5x). Mirror
     * the system setting, but cap it: the web layout is px-based and starts breaking past ~130%.
     */
    private fun applyTextZoom(settings: WebSettings) {
        val systemScale = resources.configuration.fontScale
        val cappedScale = systemScale.coerceIn(1.0f, MAX_TEXT_ZOOM_SCALE)
        settings.textZoom = (cappedScale * 100).toInt()
        Log.d(
            TAG,
            "[TEXT_ZOOM] systemFontScale=$systemScale capped=$cappedScale textZoom=${settings.textZoom}"
        )
    }

    private fun startDownload(url: String, contentDisposition: String?, mimeType: String?) {
        val filename = URLUtil.guessFileName(url, contentDisposition, mimeType)
        val request = DownloadManager.Request(Uri.parse(url)).apply {
            if (mimeType != null) setMimeType(mimeType)
            setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
            setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, filename)
        }
        val downloadManager = getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
        downloadManager.enqueue(request)
        Log.d(TAG, "[DOWNLOAD] enqueued filename=$filename url=$url")
    }

    private fun attemptLoad() {
        Log.d(TAG, "[ATTEMPT_LOAD] start_url=$START_URL")
        retryContainer.visibility = View.GONE
        if (!isNetworkAvailable()) {
            Log.w(TAG, "[ATTEMPT_LOAD] no network available, showing retry screen")
            showRetryScreen()
            return
        }
        loadingSpinner.visibility = View.VISIBLE
        webView.loadUrl(START_URL)
    }

    private fun showRetryScreen() {
        Log.d(TAG, "[RETRY_SCREEN] showing")
        loadingSpinner.visibility = View.GONE
        retryContainer.visibility = View.VISIBLE
    }

    private fun isNetworkAvailable(): Boolean {
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val network = cm.activeNetwork ?: return false
        val capabilities = cm.getNetworkCapabilities(network) ?: return false
        val available = capabilities.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_INTERNET)
        Log.d(TAG, "[NETWORK_CHECK] available=$available")
        return available
    }
}
