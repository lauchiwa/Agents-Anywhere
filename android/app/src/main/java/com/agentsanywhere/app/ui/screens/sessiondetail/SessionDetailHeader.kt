package com.agentsanywhere.app.ui.screens.sessiondetail

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.agentsanywhere.app.R
import com.agentsanywhere.app.model.ContextUsage
import com.agentsanywhere.app.model.RateLimit
import com.agentsanywhere.app.ui.designsystem.noRippleClickable
import kotlin.math.roundToInt

@Composable
internal fun SessionDetailHeader(
    title: String,
    darkMode: Boolean,
    onLeftClick: () -> Unit,
    onRightClick: () -> Unit,
    modifier: Modifier = Modifier,
    contextUsage: ContextUsage? = null,
    rateLimit: RateLimit? = null,
) {
    val surface = if (darkMode) Color(0xF218181B) else Color(0xF2FFFFFF)
    val border = if (darkMode) Color(0xFF27272A) else Color(0xFFE8E5DE)
    val text = if (darkMode) Color(0xFFFAFAFA) else Color(0xFF2F302D)

    Row(
        modifier = modifier
            .fillMaxWidth()
            .height(58.dp)
            .padding(horizontal = 18.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        HeaderImageButton(
            resId = if (darkMode) {
                R.drawable.ic_session_runtime_settings_dark
            } else {
                R.drawable.ic_session_runtime_settings_light
            },
            darkMode = darkMode,
            onClick = onLeftClick,
        )
        Row(
            modifier = Modifier
                .width(224.dp)
                .height(42.dp)
                .shadow(18.dp, CircleShape, ambientColor = Color(0x0A000000), spotColor = Color(0x0A000000))
                .clip(CircleShape)
                .background(surface)
                .border(1.dp, border, CircleShape)
                .padding(horizontal = 18.dp),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            val gaugePercent = contextUsage?.let { usage ->
                usage.percentage ?: run {
                    val total = usage.totalTokens
                    val max = usage.maxTokens
                    if (total != null && max != null && max > 0L) total.toDouble() / max * 100.0 else null
                }
            }
            val thresholdPercent = contextUsage?.let { usage ->
                val threshold = usage.autoCompactThreshold
                val max = usage.maxTokens
                if (threshold != null && max != null && max > 0L) threshold.toDouble() / max * 100.0 else 80.0
            } ?: 80.0
            val nearCompact = contextUsage?.autoCompactEnabled == true &&
                gaugePercent != null && gaugePercent >= thresholdPercent
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    text = title,
                    color = text,
                    fontSize = if (gaugePercent != null) 14.sp else 15.5.sp,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                if (gaugePercent != null) {
                    val gaugeColor = if (nearCompact) {
                        Color(0xFFDC6A5B)
                    } else if (darkMode) {
                        Color(0xFF8A8A8F)
                    } else {
                        Color(0xFF8C8B85)
                    }
                    Text(
                        text = stringResource(
                            R.string.session_context_usage,
                            gaugePercent.roundToInt(),
                        ),
                        color = gaugeColor,
                        fontSize = 11.sp,
                        lineHeight = 12.sp,
                        fontWeight = FontWeight.Medium,
                        maxLines = 1,
                    )
                }
                val rateStatus = rateLimit?.status
                if (rateStatus == "allowed_warning" || rateStatus == "rejected") {
                    val rejected = rateStatus == "rejected"
                    // Distinct throttle indicator below the gauge: an amber
                    // "quota almost full" warning, or a red "rate limited" when
                    // the CLI is actively throttling. Hidden once status is back
                    // to "allowed" (the connector keeps the snapshot current).
                    val rateColor = if (rejected) Color(0xFFDC6A5B) else Color(0xFFE0973A)
                    Text(
                        text = if (rejected) {
                            stringResource(R.string.session_rate_limited)
                        } else {
                            stringResource(R.string.session_rate_limit_warning)
                        },
                        color = rateColor,
                        fontSize = 11.sp,
                        lineHeight = 12.sp,
                        fontWeight = FontWeight.SemiBold,
                        maxLines = 1,
                    )
                }
            }
        }
        HeaderImageButton(
            resId = if (darkMode) {
                R.drawable.ic_session_agent_button_dark
            } else {
                R.drawable.ic_session_agent_button_light
            },
            darkMode = darkMode,
            onClick = onRightClick,
        )
    }
}

@Composable
internal fun HeaderVeil(
    darkMode: Boolean,
    modifier: Modifier = Modifier,
) {
    val base = if (darkMode) Color(0xFF09090B) else Color(0xFFFDFCFB)
    Box(
        modifier = modifier
            .fillMaxWidth()
            .height(88.dp)
            .background(
                Brush.verticalGradient(
                    0f to base.copy(alpha = 0.90f),
                    0.46f to base.copy(alpha = 0.72f),
                    1f to base.copy(alpha = 0f),
                ),
            ),
    )
}

@Composable
private fun HeaderImageButton(
    resId: Int,
    darkMode: Boolean,
    onClick: () -> Unit,
) {
    val surface = if (darkMode) Color(0xF218181B) else Color(0xF2FFFFFF)
    val border = if (darkMode) Color(0xFF27272A) else Color(0xFFE8E5DE)
    Box(
        modifier = Modifier
            .size(44.dp)
            .shadow(14.dp, CircleShape, ambientColor = Color(0x0A000000), spotColor = Color(0x0A000000))
            .clip(CircleShape)
            .background(surface)
            .border(1.dp, border, CircleShape)
            .noRippleClickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Image(
            painter = painterResource(resId),
            contentDescription = null,
            modifier = Modifier.size(20.dp),
            contentScale = ContentScale.Fit,
        )
    }
}
