package com.agentsanywhere.app.ui.screens.sessiondetail

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.border
import androidx.compose.foundation.background
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.DisableSelection
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.sp
import com.agentsanywhere.app.R
import com.agentsanywhere.app.feature.sessiondetail.MessageAuthor
import com.agentsanywhere.app.feature.sessiondetail.SessionDetailController
import com.agentsanywhere.app.feature.sessiondetail.SubagentProgress
import com.agentsanywhere.app.feature.sessiondetail.TimelineAttachment
import com.agentsanywhere.app.feature.sessiondetail.TimelineMessage
import com.agentsanywhere.app.feature.sessiondetail.TimelineMessageKind
import com.agentsanywhere.app.feature.sessiondetail.SkillItem
import com.agentsanywhere.app.ui.designsystem.LocalAAColors
import com.agentsanywhere.app.ui.designsystem.noRippleClickable
import com.composables.icons.lucide.ChevronDown
import com.composables.icons.lucide.ChevronRight
import com.composables.icons.lucide.Copy
import com.composables.icons.lucide.Lucide
import com.composables.icons.lucide.RefreshCw
import com.valentinilk.shimmer.shimmer
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.distinctUntilChanged
import java.time.Duration
import java.time.Instant
import java.time.format.DateTimeParseException
import kotlinx.coroutines.launch
import kotlin.math.abs

private const val SESSION_WELCOME_WRITE_MS = 58L
private const val SESSION_WELCOME_ERASE_MS = 22L
private const val SESSION_WELCOME_HOLD_MS = 15_000L
private const val LOAD_OLDER_VISIBLE_THRESHOLD = 3
private const val RETURN_TO_LATEST_ANIMATION_WINDOW = 12
private val AUTO_FOLLOW_RESUME_THRESHOLD = 8.dp
private val AUTO_FOLLOW_DRAG_PAUSE_THRESHOLD = 32.dp
private val TimelineMessageOrder = compareBy<TimelineMessage> { it.orderSeq }
    .thenBy { it.updatedSeq }
    .thenBy { it.id }
private val SessionWelcomeFontFamily = FontFamily(
    Font(R.font.newsreader_opsz_wght, FontWeight(650)),
)

private sealed interface TimelineRenderItem {
    val key: String
    val messages: List<TimelineMessage>

    data class Single(val message: TimelineMessage) : TimelineRenderItem {
        override val key: String = message.id
        override val messages: List<TimelineMessage> = listOf(message)
    }

    data class ToolRun(override val messages: List<TimelineMessage>) : TimelineRenderItem {
        override val key: String = "tool-run:${messages.joinToString(":") { it.id }}"
    }
}

@Composable
internal fun SessionDetailLoadingState(darkMode: Boolean) {
    val baseColor = if (darkMode) Color(0xFF1E1E22) else Color(0xFFEDEBE6)

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .shimmer()
            .padding(horizontal = 20.dp),
        verticalArrangement = Arrangement.spacedBy(18.dp),
    ) {
        item(key = "loading-top-space") { Spacer(Modifier.height(82.dp)) }
        item(key = "loading-agent-1") {
            AgentMessageSkeleton(baseColor = baseColor, widths = listOf(0.88f, 0.72f, 0.54f))
        }
        item(key = "loading-tool") {
            ToolMessageSkeleton(baseColor = baseColor)
        }
        item(key = "loading-user-1") {
            UserMessageSkeleton(baseColor = baseColor, widthFraction = 0.38f)
        }
        item(key = "loading-agent-2") {
            AgentMessageSkeleton(baseColor = baseColor, widths = listOf(0.80f, 0.92f, 0.66f, 0.44f))
        }
        item(key = "loading-bottom-space") { Spacer(Modifier.height(190.dp)) }
    }
}

@Composable
private fun AgentMessageSkeleton(baseColor: Color, widths: List<Float>) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 4.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        widths.forEachIndexed { index, width ->
            SkeletonBlock(
                modifier = Modifier
                    .fillMaxWidth(width)
                    .height(if (index == 0) 18.dp else 16.dp),
                baseColor = baseColor,
                shape = RoundedCornerShape(8.dp),
            )
        }
    }
}

@Composable
private fun UserMessageSkeleton(baseColor: Color, widthFraction: Float) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.End,
    ) {
        SkeletonBlock(
            modifier = Modifier
                .fillMaxWidth(widthFraction)
                .height(52.dp),
            baseColor = baseColor,
            shape = RoundedCornerShape(22.dp),
        )
    }
}

@Composable
private fun ToolMessageSkeleton(baseColor: Color) {
    Row(
        modifier = Modifier.padding(horizontal = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        SkeletonBlock(
            modifier = Modifier.size(14.dp),
            baseColor = baseColor,
            shape = CircleShape,
        )
        SkeletonBlock(
            modifier = Modifier
                .width(112.dp)
                .height(13.dp),
            baseColor = baseColor,
            shape = RoundedCornerShape(7.dp),
        )
    }
}

@Composable
private fun SkeletonBlock(
    modifier: Modifier,
    baseColor: Color,
    shape: androidx.compose.ui.graphics.Shape,
) {
    Box(
        modifier = modifier
            .clip(shape)
            .background(baseColor),
    )
}

@Composable
internal fun MessageList(
    messages: List<TimelineMessage>,
    darkMode: Boolean,
    sessionId: String,
    controller: SessionDetailController,
    forceLatestRequest: Int,
    streamLatestRequest: Int,
    workingLabel: String?,
    hasMore: Boolean,
    loadingOlder: Boolean,
    onLoadOlder: () -> Unit,
    onPreviewAttachment: (TimelineAttachment) -> Unit,
    onCopyMessage: (String) -> Unit,
    onOpenFile: (String) -> Unit,
) {
    val listState = rememberLazyListState()
    val scope = rememberCoroutineScope()
    val density = LocalDensity.current
    val resumeThresholdPx = with(density) { AUTO_FOLLOW_RESUME_THRESHOLD.roundToPx() }
    val dragPauseThresholdPx = with(density) { AUTO_FOLLOW_DRAG_PAUSE_THRESHOLD.toPx() }
    val latestMessages by rememberUpdatedState(messages)
    val latestWorkingLabel by rememberUpdatedState(workingLabel)
    var lockedMessages by remember(sessionId) { mutableStateOf<List<TimelineMessage>?>(null) }
    var lockedWorkingLabel by remember(sessionId) { mutableStateOf<String?>(null) }
    val displayMessages = lockedMessages ?: messages
    val displayWorkingLabel = if (lockedMessages != null) lockedWorkingLabel else workingLabel
    val timelineItems = remember(displayMessages) { groupTimelineMessages(displayMessages) }
    val childrenByParent = remember(displayMessages) { buildChildrenByParent(displayMessages) }
    val agentTurnCopyTextByItem = remember(timelineItems, displayWorkingLabel) {
        buildAgentTurnCopyTextByItem(timelineItems, displayWorkingLabel != null)
    }
    var showScrollToBottom by remember { mutableStateOf(false) }
    var autoFollowLatest by remember(sessionId) { mutableStateOf(true) }
    var userPausedAutoFollow by remember(sessionId) { mutableStateOf(false) }

    fun releaseReadLock() {
        lockedMessages = null
        lockedWorkingLabel = null
        userPausedAutoFollow = false
        autoFollowLatest = true
    }

    fun pauseAutoFollowWithSnapshot() {
        if (lockedMessages == null) {
            lockedMessages = latestMessages
            lockedWorkingLabel = latestWorkingLabel
        }
        userPausedAutoFollow = true
        autoFollowLatest = false
    }

    LaunchedEffect(messages, lockedMessages) {
        val locked = lockedMessages ?: return@LaunchedEffect
        val merged = mergeOlderMessagesIntoLock(
            lockedMessages = locked,
            latestMessages = messages,
        )
        if (merged.size != locked.size) {
            lockedMessages = merged
        }
    }

    LaunchedEffect(listState) {
        var lastPosition = listState.firstVisibleItemIndex * 1_000 + listState.firstVisibleItemScrollOffset
        var lastTime = System.nanoTime()
        snapshotFlow {
            (listState.firstVisibleItemIndex * 1_000 + listState.firstVisibleItemScrollOffset) to listState.isScrollInProgress
        }.collectLatest { (position, scrolling) ->
                val now = System.nanoTime()
                val elapsedMs = ((now - lastTime) / 1_000_000).coerceAtLeast(1)
                val slowEnough = abs(position - lastPosition) / elapsedMs < 2
                lastPosition = position
                lastTime = now
                if (position > 0 && (slowEnough || !scrolling)) {
                    delay(120)
                    showScrollToBottom = listState.firstVisibleItemIndex > 0 || listState.firstVisibleItemScrollOffset > 0
                } else {
                    showScrollToBottom = false
                }
        }
    }

    LaunchedEffect(listState, resumeThresholdPx) {
        snapshotFlow {
            Triple(
                listState.isAtLatest(),
                listState.isNearLatest(resumeThresholdPx),
                listState.isScrollInProgress,
            )
        }
            .distinctUntilChanged()
            .collectLatest { (atLatest, nearLatest, scrolling) ->
                if (atLatest && !scrolling) {
                    releaseReadLock()
                } else if (nearLatest && !scrolling && !userPausedAutoFollow) {
                    autoFollowLatest = true
                }
            }
    }

    LaunchedEffect(forceLatestRequest) {
        if (forceLatestRequest > 0) {
            releaseReadLock()
            listState.scrollToItem(0)
        }
    }

    LaunchedEffect(streamLatestRequest) {
        if (streamLatestRequest > 0 && autoFollowLatest && !userPausedAutoFollow && !listState.isScrollInProgress) {
            listState.scrollToItem(0)
        }
    }

    LaunchedEffect(listState, hasMore, loadingOlder, displayMessages.size) {
        snapshotFlow {
            val layout = listState.layoutInfo
            val total = layout.totalItemsCount
            val lastVisible = layout.visibleItemsInfo.maxOfOrNull { it.index } ?: -1
            total > 0 && lastVisible >= total - LOAD_OLDER_VISIBLE_THRESHOLD
        }
            .distinctUntilChanged()
            .collectLatest { nearOldest ->
                if (nearOldest && hasMore && !loadingOlder) {
                    onLoadOlder()
                }
            }
    }

    Box(Modifier.fillMaxSize()) {
        SessionSelectionContainer(modifier = Modifier.fillMaxSize()) {
            LazyColumn(
                state = listState,
                reverseLayout = true,
                modifier = Modifier
                    .fillMaxSize()
                    .imePadding()
                    .pointerInput(sessionId, dragPauseThresholdPx) {
                        awaitPointerEventScope {
                            while (true) {
                                val down = awaitPointerEvent(PointerEventPass.Initial)
                                    .changes
                                    .firstOrNull { it.pressed && !it.previousPressed }
                                    ?: continue
                                val pointerId = down.id
                                val startY = down.position.y

                                while (true) {
                                    val event = awaitPointerEvent(PointerEventPass.Initial)
                                    val change = event.changes.firstOrNull { it.id == pointerId }
                                        ?: event.changes.firstOrNull { it.pressed }
                                        ?: break
                                    if (!change.pressed) break
                                    if (abs(change.position.y - startY) >= dragPauseThresholdPx) {
                                        pauseAutoFollowWithSnapshot()
                                    }
                                }
                            }
                        }
                    }
                    .padding(horizontal = 20.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                item(key = "bottom-space") { Spacer(Modifier.height(168.dp)) }
                if (displayWorkingLabel != null) {
                    item(key = "working-indicator") {
                        DisableSelection {
                            WorkingIndicator(label = displayWorkingLabel, darkMode = darkMode)
                        }
                    }
                }
                items(timelineItems.asReversed(), key = { it.key }) { item ->
                    Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
                        when (item) {
                            is TimelineRenderItem.Single -> TimelineMessageRow(
                                message = item.message,
                                darkMode = darkMode,
                                listState = listState,
                                sessionId = sessionId,
                                controller = controller,
                                onPreviewAttachment = onPreviewAttachment,
                                onCopyMessage = onCopyMessage,
                                onOpenFile = onOpenFile,
                                childrenByParent = childrenByParent,
                            )
                            is TimelineRenderItem.ToolRun -> ToolRunGroup(
                                messages = item.messages,
                                darkMode = darkMode,
                                listState = listState,
                                childrenByParent = childrenByParent,
                                onOpenFile = onOpenFile,
                            )
                        }
                        agentTurnCopyTextByItem[item.key]?.let { copyText ->
                            DisableSelection {
                                AgentReplyCopyAction(
                                    darkMode = darkMode,
                                    copyText = copyText,
                                    onCopyMessage = onCopyMessage,
                                )
                            }
                        }
                    }
                }
                if (loadingOlder) {
                    item(key = "loading-older") {
                        DisableSelection {
                            OlderMessagesLoadingIndicator(darkMode = darkMode)
                        }
                    }
                }
                item(key = "top-space") { Spacer(Modifier.height(74.dp)) }
            }
        }

        if (showScrollToBottom) {
            ScrollToBottomButton(
                darkMode = darkMode,
                onClick = {
                    scope.launch {
                        listState.animateToLatestFromAnywhere()
                        releaseReadLock()
                        listState.scrollToItem(0)
                    }
                },
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .imePadding()
                    .padding(bottom = 140.dp),
            )
        }
    }
}

private suspend fun LazyListState.animateToLatestFromAnywhere() {
    if (firstVisibleItemIndex > RETURN_TO_LATEST_ANIMATION_WINDOW) {
        scrollToItem(RETURN_TO_LATEST_ANIMATION_WINDOW)
    }
    animateScrollToItem(0)
}

private fun mergeOlderMessagesIntoLock(
    lockedMessages: List<TimelineMessage>,
    latestMessages: List<TimelineMessage>,
): List<TimelineMessage> {
    val firstLocked = lockedMessages.minWithOrNull(TimelineMessageOrder) ?: return lockedMessages
    val lockedIds = lockedMessages.mapTo(mutableSetOf()) { it.id }
    val olderMessages = latestMessages.filter { message ->
        message.id !in lockedIds && TimelineMessageOrder.compare(message, firstLocked) < 0
    }
    if (olderMessages.isEmpty()) return lockedMessages
    return (olderMessages + lockedMessages)
        .distinctBy { it.id }
        .sortedWith(TimelineMessageOrder)
}

private fun LazyListState.isNearLatest(thresholdPx: Int): Boolean {
    return firstVisibleItemIndex == 0 && firstVisibleItemScrollOffset <= thresholdPx
}

private fun LazyListState.isAtLatest(): Boolean {
    return firstVisibleItemIndex == 0 && firstVisibleItemScrollOffset == 0
}

@Composable
private fun AgentReplyCopyAction(
    darkMode: Boolean,
    copyText: String,
    onCopyMessage: (String) -> Unit,
) {
    val divider = if (darkMode) Color(0x4A3F3F46) else Color(0x332F2F33)
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(start = 4.dp, end = 4.dp, top = 3.dp),
        verticalArrangement = Arrangement.spacedBy(5.dp),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(1.dp)
                .background(divider),
        )
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.Start,
        ) {
            MessageCopyButton(
                darkMode = darkMode,
                label = stringResource(R.string.session_copy_reply),
                onClick = { onCopyMessage(copyText) },
            )
        }
    }
}

private fun groupTimelineMessages(messages: List<TimelineMessage>): List<TimelineRenderItem> {
    val result = mutableListOf<TimelineRenderItem>()
    val pendingTools = mutableListOf<TimelineMessage>()
    // Subagent (Task) output arrives as separate timeline items that carry the
    // parent Task's item id. Those get nested under the parent card, so they
    // must be pulled out of the top-level flow here.
    val presentIds = messages.mapTo(mutableSetOf()) { it.id }

    fun flushTools() {
        when (pendingTools.size) {
            0 -> Unit
            1 -> result += TimelineRenderItem.Single(pendingTools.first())
            else -> result += TimelineRenderItem.ToolRun(pendingTools.toList())
        }
        pendingTools.clear()
    }

    for (message in messages) {
        if (message.parentItemId != null && message.parentItemId in presentIds) {
            continue
        }
        if (message.isToolRunItem()) {
            pendingTools += message
        } else {
            flushTools()
            result += TimelineRenderItem.Single(message)
        }
    }
    flushTools()
    return result
}

private fun buildChildrenByParent(
    messages: List<TimelineMessage>,
): Map<String, List<TimelineMessage>> {
    val presentIds = messages.mapTo(mutableSetOf()) { it.id }
    return messages
        .filter { it.parentItemId != null && it.parentItemId in presentIds }
        .sortedWith(TimelineMessageOrder)
        .groupBy { it.parentItemId!! }
}

private fun buildAgentTurnCopyTextByItem(
    items: List<TimelineRenderItem>,
    hideLatestTurn: Boolean,
): Map<String, String> {
    val latestTurnId = if (hideLatestTurn) {
        items.asReversed()
            .asSequence()
            .flatMap { it.messages.asReversed().asSequence() }
            .firstOrNull { it.turnId != null }
            ?.turnId
    } else {
        null
    }
    val turnOrder = mutableListOf<String>()
    val textByTurn = linkedMapOf<String, MutableList<String>>()
    val lastItemKeyByTurn = linkedMapOf<String, String>()

    items.forEach { item ->
        item.messages.forEach { message ->
            val turnKey = message.turnId ?: "message:${message.id}"
            if (message.turnId != null || message.isCopyableAgentText()) {
                lastItemKeyByTurn[turnKey] = item.key
            }
            val text = message.agentCopyText()
            if (text.isNotBlank()) {
                if (turnKey !in textByTurn) {
                    turnOrder += turnKey
                    textByTurn[turnKey] = mutableListOf()
                }
                textByTurn.getValue(turnKey) += text
            }
        }
    }

    return buildMap {
        turnOrder.forEach { turnKey ->
            if (turnKey == latestTurnId) return@forEach
            val copyText = textByTurn[turnKey]
                .orEmpty()
                .joinToString("\n\n")
                .trim()
            val lastItemKey = lastItemKeyByTurn[turnKey]
            if (copyText.isNotBlank() && lastItemKey != null) {
                put(lastItemKey, copyText)
            }
        }
    }
}

private fun TimelineMessage.isCopyableAgentText(): Boolean {
    return kind == TimelineMessageKind.Text && author == MessageAuthor.Agent
}

private fun TimelineMessage.agentCopyText(): String {
    return if (isCopyableAgentText()) text.trimEnd('\r', '\n') else ""
}

private fun TimelineMessage.isToolRunItem(): Boolean {
    return kind == TimelineMessageKind.Command ||
        kind == TimelineMessageKind.FileChange ||
        kind == TimelineMessageKind.ToolCall
}

@Composable
private fun OlderMessagesLoadingIndicator(darkMode: Boolean) {
    val color = if (darkMode) Color(0xFFEDEDEF) else Color(0xFF2F2F33)
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 8.dp),
        contentAlignment = Alignment.Center,
    ) {
        CircularProgressIndicator(
            color = color,
            strokeWidth = 2.dp,
            modifier = Modifier.size(22.dp),
        )
    }
}

@Composable
private fun ToolRunGroup(
    messages: List<TimelineMessage>,
    darkMode: Boolean,
    listState: LazyListState,
    childrenByParent: Map<String, List<TimelineMessage>> = emptyMap(),
    onOpenFile: (String) -> Unit = {},
) {
    val primary = if (darkMode) Color(0xFFFAFAFA) else Color(0xFF2B2C29)
    val muted = if (darkMode) Color(0xFFA1A1AA) else Color(0xFF7C7B76)
    val surface = if (darkMode) Color(0x1018181B) else Color(0x14F1F0ED)
    val haptic = LocalHapticFeedback.current
    var expanded by remember(messages.joinToString(":") { it.id }) { mutableStateOf(false) }
    var cardTop by remember(messages.joinToString(":") { it.id }) { mutableStateOf<Float?>(null) }
    var lockedTop by remember(messages.joinToString(":") { it.id }) { mutableStateOf<Float?>(null) }

    fun toggleExpanded() {
        haptic.performHapticFeedback(HapticFeedbackType.LongPress)
        lockedTop = cardTop
        expanded = !expanded
    }

    val modifier = Modifier
        .fillMaxWidth()
        .padding(horizontal = 4.dp)
        .onGloballyPositioned {
            val nextTop = it.positionInWindow().y
            val delta = (lockedTop ?: nextTop) - nextTop
            if (abs(delta) > 1f) listState.dispatchRawDelta(delta)
            lockedTop = null
            cardTop = nextTop
        }

    if (!expanded) {
        Row(
            modifier = modifier
                .heightIn(min = 34.dp)
                .clip(RoundedCornerShape(8.dp))
                .background(surface)
                .noRippleClickable(onClick = ::toggleExpanded)
                .padding(horizontal = 6.dp, vertical = 6.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            ChevronRightGlyph(muted)
            PngToolIcon(
                lightRes = R.drawable.ic_tool_call_light,
                darkRes = R.drawable.ic_tool_call_dark,
                darkMode = darkMode,
                sizeDp = 16,
            )
            Text(
                text = toolRunSummary(messages),
                modifier = Modifier.weight(1f),
                color = muted,
                fontSize = 13.sp,
                fontWeight = FontWeight.Bold,
                fontFamily = FontFamily.Monospace,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            CompactStatusPill(label = toolRunStatus(messages), darkMode = darkMode)
        }
        return
    }

    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = 34.dp)
                .noRippleClickable(onClick = ::toggleExpanded)
                .padding(horizontal = 6.dp, vertical = 6.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            ChevronDownGlyph(muted)
            Text(
                text = toolRunSummary(messages),
                modifier = Modifier.weight(1f),
                color = primary,
                fontSize = 13.sp,
                fontWeight = FontWeight.Bold,
                fontFamily = FontFamily.Monospace,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            CompactStatusPill(label = toolRunStatus(messages), darkMode = darkMode)
        }
        messages.forEach { message ->
            ToolActivityCard(
                message = message,
                darkMode = darkMode,
                listState = listState,
                embedded = true,
                children = childrenByParent[message.id].orEmpty(),
                onOpenFile = onOpenFile,
            )
        }
    }
}

@Composable
private fun toolRunSummary(messages: List<TimelineMessage>): String {
    val commands = messages.count { it.kind == TimelineMessageKind.Command }
    val fileChanges = messages.count { it.kind == TimelineMessageKind.FileChange && it.title != "Added" }
    val createdFiles = messages.count { it.kind == TimelineMessageKind.FileChange && it.title == "Added" }
    val tools = messages.count { it.kind == TimelineMessageKind.ToolCall }
    val parts = buildList {
        if (commands > 0) add(stringResource(R.string.session_tool_summary_commands, commands))
        if (fileChanges > 0) add(stringResource(R.string.session_tool_summary_changed_files, fileChanges))
        if (createdFiles > 0) add(stringResource(R.string.session_tool_summary_created_files, createdFiles))
        if (tools > 0) add(stringResource(R.string.session_tool_summary_items, tools))
    }
    return parts.joinToString(", ").ifBlank {
        stringResource(R.string.session_tool_summary_items, messages.size)
    }
}

private fun toolRunStatus(messages: List<TimelineMessage>): String {
    return when {
        messages.any { it.status == "failed" } -> "Failed"
        messages.any { it.status == "running" } -> "Running"
        messages.any { it.status == "pending" } -> "Pending"
        messages.any { it.status == "waiting_approval" } -> "Approval"
        messages.any { it.status == "cancelled" } -> "Cancelled"
        messages.any { it.status == "interrupted" } -> "Stopped"
        else -> "Done"
    }
}

@Composable
private fun WorkingIndicator(label: String, darkMode: Boolean) {
    val muted = if (darkMode) Color(0xFFA1A1AA) else Color(0xFF7C7B76)
    val pulse by rememberInfiniteTransition(label = "working-indicator-pulse").animateFloat(
        initialValue = 0.35f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 760),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "working-indicator-alpha",
    )
    Row(
        modifier = Modifier
            .padding(horizontal = 4.dp)
            .alpha(pulse),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        PngToolIcon(
            lightRes = R.drawable.ic_reasoning_sparkles_light,
            darkRes = R.drawable.ic_reasoning_sparkles_dark,
            darkMode = darkMode,
            sizeDp = 14,
        )
        Text(
            text = label,
            color = muted,
            fontSize = 13.sp,
            fontWeight = FontWeight.Bold,
        )
    }
}

@Composable
private fun ScrollToBottomButton(
    darkMode: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val surface = if (darkMode) Color(0xFF2A2A2D) else Color.White
    val border = if (darkMode) Color(0xFF3F3F46) else Color(0xFFE8E8E8)
    val icon = if (darkMode) Color(0xFFEDEDEF) else Color.Black

    Box(
        modifier = modifier
            .size(48.dp)
            .shadow(10.dp, CircleShape, ambientColor = Color(0x22000000), spotColor = Color(0x2A000000))
            .clip(CircleShape)
            .background(surface)
            .border(1.dp, border, CircleShape)
            .noRippleClickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        ArrowDownGlyph(icon, sizeDp = 23)
    }
}

@Composable
private fun TimelineMessageRow(
    message: TimelineMessage,
    darkMode: Boolean,
    listState: LazyListState,
    sessionId: String,
    controller: SessionDetailController,
    onPreviewAttachment: (TimelineAttachment) -> Unit,
    onCopyMessage: (String) -> Unit,
    onOpenFile: (String) -> Unit,
    childrenByParent: Map<String, List<TimelineMessage>> = emptyMap(),
) {
    when (message.kind) {
        TimelineMessageKind.Reasoning -> ReasoningSection(message, darkMode)
        TimelineMessageKind.Command,
        TimelineMessageKind.FileChange,
        TimelineMessageKind.ToolCall -> ToolActivityCard(
            message = message,
            darkMode = darkMode,
            listState = listState,
            children = childrenByParent[message.id].orEmpty(),
            onOpenFile = onOpenFile,
        )
        TimelineMessageKind.Notification -> NotificationCard(message, darkMode, onCopyMessage)
        TimelineMessageKind.System -> ToolPlaceholder(message, darkMode)
        TimelineMessageKind.Compact -> CompactSeparator(message, darkMode)
        TimelineMessageKind.SkillListing -> SkillListingCard(message, darkMode)
        TimelineMessageKind.DeferredToolsDelta -> DeferredToolsDeltaPill(message, darkMode)
        TimelineMessageKind.InvokedSkills -> InvokedSkillsPill(message, darkMode)
        TimelineMessageKind.Text -> when (message.author) {
            MessageAuthor.User -> UserBubble(message, darkMode, sessionId, controller, onPreviewAttachment, onCopyMessage)
            MessageAuthor.Agent -> AgentMarkdownText(message.text, darkMode, onOpenFile = onOpenFile)
            MessageAuthor.Tool -> ToolPlaceholder(message, darkMode)
        }
    }
}

@Composable
private fun UserBubble(
    message: TimelineMessage,
    darkMode: Boolean,
    sessionId: String,
    controller: SessionDetailController,
    onPreviewAttachment: (TimelineAttachment) -> Unit,
    onCopyMessage: (String) -> Unit,
) {
    BoxWithConstraints(Modifier.fillMaxWidth()) {
        val maxBubbleWidth = maxWidth * 0.78f
        val meta = when (message.status) {
            "failed" -> stringResource(R.string.session_status_failed)
            else -> ""
        }

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.End,
        ) {
            Column(
                horizontalAlignment = Alignment.End,
                verticalArrangement = Arrangement.spacedBy(7.dp),
            ) {
                val hasAttachments = message.attachments.isNotEmpty()
                val text = message.text
                    .trimEnd('\r', '\n')
                    .takeUnless { it == "(No text content.)" && hasAttachments }
                    .orEmpty()
                var expanded by remember(message.id, text) { mutableStateOf(false) }
                var canExpand by remember(message.id, text) { mutableStateOf(false) }
                UserAttachmentStrip(
                    attachments = message.attachments,
                    darkMode = darkMode,
                    sessionId = sessionId,
                    controller = controller,
                    onPreviewAttachment = onPreviewAttachment,
                )
                if (text.isNotBlank()) {
                    Row(
                        modifier = Modifier.widthIn(max = maxBubbleWidth + 38.dp),
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        verticalAlignment = Alignment.Bottom,
                    ) {
                        DisableSelection {
                            MessageCopyButton(
                                darkMode = darkMode,
                                onClick = { onCopyMessage(text) },
                                modifier = Modifier.padding(bottom = 3.dp),
                            )
                        }
                        Box(
                            modifier = Modifier
                                .widthIn(max = maxBubbleWidth)
                                .clip(RoundedCornerShape(22.dp))
                                .background(if (darkMode) Color(0xFF2A2A2D) else Color(0xFFF1F0ED))
                                .padding(horizontal = 17.dp, vertical = 13.dp),
                        ) {
                            Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
                                Text(
                                    text = text,
                                    color = if (darkMode) Color(0xFFF4F4F5) else Color(0xFF242522),
                                    fontSize = 16.5.sp,
                                    lineHeight = 24.sp,
                                    fontWeight = FontWeight.Normal,
                                    maxLines = if (expanded) Int.MAX_VALUE else 8,
                                    overflow = TextOverflow.Ellipsis,
                                    onTextLayout = { result ->
                                        if (!expanded) canExpand = result.hasVisualOverflow
                                    },
                                )
                                if (canExpand || expanded) {
                                    DisableSelection {
                                        Text(
                                            text = if (expanded) {
                                                stringResource(R.string.session_show_less)
                                            } else {
                                                stringResource(R.string.session_read_more)
                                            },
                                            color = Color(0xFFEAB308),
                                            fontSize = 12.sp,
                                            fontWeight = FontWeight.Bold,
                                            modifier = Modifier.noRippleClickable { expanded = !expanded },
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
                if (meta.isNotBlank()) {
                    DisableSelection {
                        Text(
                            text = meta,
                            color = if (message.status == "failed") Color(0xFFF87171) else if (darkMode) Color(0xFFA1A1AA) else Color(0xFF7C7B76),
                            fontSize = 11.sp,
                            fontWeight = FontWeight.SemiBold,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun MessageCopyButton(
    darkMode: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    label: String? = null,
) {
    val iconRes = if (darkMode) R.drawable.ic_copy_bash_command_light else R.drawable.ic_copy_bash_command_dark
    val contentColor = if (darkMode) Color(0xFFA1A1AA) else Color(0xFF7C7B76)
    Row(
        modifier = modifier
            .height(30.dp)
            .then(
                if (label == null) {
                    Modifier
                        .width(30.dp)
                        .clip(CircleShape)
                } else {
                    Modifier.padding(start = 8.dp, end = 10.dp)
                },
            )
            .noRippleClickable(onClick = onClick),
        horizontalArrangement = Arrangement.spacedBy(if (label == null) 0.dp else 9.dp, Alignment.CenterHorizontally),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Image(
            painter = painterResource(iconRes),
            contentDescription = label ?: stringResource(R.string.common_copy),
            modifier = Modifier.size(17.dp),
        )
        if (label != null) {
            Text(
                text = label,
                color = contentColor,
                fontSize = 12.sp,
                lineHeight = 14.sp,
                fontWeight = FontWeight.SemiBold,
            )
        }
    }
}

@Composable
private fun UserAttachmentStrip(
    attachments: List<TimelineAttachment>,
    darkMode: Boolean,
    sessionId: String,
    controller: SessionDetailController,
    onPreviewAttachment: (TimelineAttachment) -> Unit,
) {
    if (attachments.isEmpty()) return
    Column(
        horizontalAlignment = Alignment.End,
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        attachments.forEach { attachment ->
            if (attachment.isImage) {
                RemoteAttachmentImage(
                    sessionId = sessionId,
                    controller = controller,
                    attachment = attachment,
                    modifier = Modifier
                        .size(width = 196.dp, height = 142.dp)
                        .clip(RoundedCornerShape(14.dp))
                        .noRippleClickable { onPreviewAttachment(attachment) },
                    contentScale = ContentScale.Crop,
                )
            } else {
                UserFileAttachmentCard(
                    attachment = attachment,
                    darkMode = darkMode,
                )
            }
        }
    }
}

@Composable
private fun UserFileAttachmentCard(
    attachment: TimelineAttachment,
    darkMode: Boolean,
) {
    val surface = if (darkMode) Color(0xFF2A2A2D) else Color(0xFFF1F0ED)
    val iconSurface = if (darkMode) Color(0xFF18181B) else Color.White.copy(alpha = 0.86f)
    val text = if (darkMode) Color(0xFFF4F4F5) else Color(0xFF242522)
    val muted = if (darkMode) Color(0xFFA1A1AA) else Color(0xFF7C7B76)
    val iconRes = if (darkMode) R.drawable.ic_attachment_file_white else R.drawable.ic_attachment_file_black

    Row(
        modifier = Modifier
            .width(224.dp)
            .height(72.dp)
            .clip(RoundedCornerShape(18.dp))
            .background(surface)
            .padding(10.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(42.dp)
                .clip(RoundedCornerShape(14.dp))
                .background(iconSurface),
            contentAlignment = Alignment.Center,
        ) {
            Image(
                painter = painterResource(iconRes),
                contentDescription = null,
                modifier = Modifier.size(22.dp),
            )
        }
        Column(Modifier.weight(1f)) {
            Text(
                text = attachment.name,
                color = text,
                fontSize = 13.sp,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = formatBytes(attachment.size),
                color = muted,
                fontSize = 11.sp,
                maxLines = 1,
            )
        }
    }
}

@Composable
private fun CompactSeparator(message: TimelineMessage, darkMode: Boolean) {
    // Context-compaction boundary: the CLI dropped earlier history to reclaim
    // the window. Render a centered, non-expandable divider so the user
    // understands why a chunk of the conversation vanished; the subtitle carries
    // the "N -> M" token counts when the connector supplied them.
    val muted = if (darkMode) Color(0xFFA1A1AA) else Color(0xFF7C7B76)
    val line = if (darkMode) Color(0x33FFFFFF) else Color(0x1F000000)
    val label = if (message.subtitle.isNotBlank()) {
        stringResource(R.string.session_context_compacted_tokens, message.subtitle)
    } else {
        stringResource(R.string.session_context_compacted)
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 4.dp, vertical = 2.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .weight(1f)
                .height(1.dp)
                .background(line),
        )
        Text(
            text = label,
            color = muted,
            fontSize = 11.sp,
            fontWeight = FontWeight.Medium,
        )
        Box(
            modifier = Modifier
                .weight(1f)
                .height(1.dp)
                .background(line),
        )
    }
}

@Composable
private fun NotificationCard(
    message: TimelineMessage,
    darkMode: Boolean,
    onCopyMessage: ((String) -> Unit)? = null,
) {
    // CLI-initiated Notification hook (include_hook_events). A message asking for
    // the user's attention that has no other channel; render an amber-accented
    // note distinct from ordinary tool/system output. The connector-supplied
    // title arrives in message.title (subtitle kept as a legacy fallback).
    val accent = if (darkMode) Color(0xFFE0973A) else Color(0xFFB9791F)
    val bg = if (darkMode) Color(0x1FE0973A) else Color(0x14B9791F)
    val body = if (darkMode) Color(0xFFE4E3DE) else Color(0xFF1F1E1B)
    val heading = message.title.ifBlank { message.subtitle }.ifBlank {
        stringResource(R.string.session_notification)
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(10.dp))
            .background(bg)
            .padding(start = 12.dp, end = 4.dp, top = 9.dp, bottom = 9.dp),
        horizontalArrangement = Arrangement.spacedBy(9.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            Text(
                text = heading,
                color = accent,
                fontSize = 12.sp,
                fontWeight = FontWeight.SemiBold,
            )
            if (message.text.isNotBlank()) {
                Text(
                    text = message.text,
                    color = body,
                    fontSize = 13.sp,
                    lineHeight = 18.sp,
                )
            }
        }
        if (onCopyMessage != null && message.text.isNotBlank()) {
            MessageCopyButton(
                darkMode = darkMode,
                onClick = { onCopyMessage(message.text.trimEnd('\r', '\n')) },
            )
        }
    }
}

@Composable
private fun ReasoningSection(message: TimelineMessage, darkMode: Boolean) {
    val muted = if (darkMode) Color(0xFFA1A1AA) else Color(0xFF7C7B76)
    val streaming = message.status == "running"
    val durationSeconds = if (streaming) null else reasoningDurationSeconds(message)
    val label = when {
        streaming -> stringResource(R.string.session_reasoning_thinking)
        durationSeconds != null -> stringResource(R.string.session_reasoning_duration, durationSeconds)
        else -> stringResource(R.string.session_reasoning)
    }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 4.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            PngToolIcon(
                lightRes = R.drawable.ic_reasoning_sparkles_light,
                darkRes = R.drawable.ic_reasoning_sparkles_dark,
                darkMode = darkMode,
                sizeDp = 14,
            )
            Text(
                text = label,
                color = muted,
                fontSize = 13.sp,
                fontWeight = FontWeight.Bold,
            )
        }
        if (message.redacted) {
            Text(
                text = stringResource(R.string.session_reasoning_redacted),
                color = muted,
                fontSize = 14.sp,
                lineHeight = 21.sp,
                fontStyle = FontStyle.Italic,
                fontWeight = FontWeight.Medium,
            )
        } else if (message.text.isNotBlank()) {
            AgentMarkdownText(message.text, darkMode)
        }
    }
}

// Thinking duration is derived client-side from the item's own timestamps: the
// connector stamps createdAt when the reasoning block opens and completedAt when
// it converges. Returns null when either bound is missing or unparseable, or the
// span is under a second (nothing worth showing).
private fun reasoningDurationSeconds(message: TimelineMessage): Long? {
    val startedRaw = message.createdAt.ifBlank { return null }
    val finishedRaw = message.completedAt?.ifBlank { null } ?: return null
    return try {
        val seconds = Duration.between(Instant.parse(startedRaw), Instant.parse(finishedRaw)).seconds
        seconds.takeIf { it > 0 }
    } catch (_: DateTimeParseException) {
        null
    }
}

@Composable
private fun ToolActivityCard(
    message: TimelineMessage,
    darkMode: Boolean,
    listState: LazyListState,
    embedded: Boolean = false,
    children: List<TimelineMessage> = emptyList(),
    onOpenFile: (String) -> Unit = {},
) {
    val surface = if (darkMode) Color(0xFF18181B) else Color(0xFFF1F0ED)
    val border = if (darkMode) Color(0xFF27272A) else Color(0xFFE4E1DB)
    val primary = if (darkMode) Color(0xFFFAFAFA) else Color(0xFF2B2C29)
    val muted = if (darkMode) Color(0xFFA1A1AA) else Color(0xFF7C7B76)
    val collapsedSurface = if (darkMode) Color(0x1018181B) else Color(0x12F1F0ED)
    val hasChildren = children.isNotEmpty()
    val expandable = hasChildren ||
        message.kind == TimelineMessageKind.Command ||
        message.kind == TimelineMessageKind.FileChange ||
        (message.kind == TimelineMessageKind.ToolCall && message.hasToolCallDetail)
    val haptic = LocalHapticFeedback.current
    var expanded by remember(message.id) { mutableStateOf(false) }
    var cardTop by remember(message.id) { mutableStateOf<Float?>(null) }
    var lockedTop by remember(message.id) { mutableStateOf<Float?>(null) }
    fun toggleExpanded() {
        haptic.performHapticFeedback(HapticFeedbackType.LongPress)
        lockedTop = cardTop
        expanded = !expanded
    }
    val target = message.toolSummaryTarget()
    val cardModifier = Modifier
        .fillMaxWidth()
        .onGloballyPositioned {
            val nextTop = it.positionInWindow().y
            val delta = (lockedTop ?: nextTop) - nextTop
            if (abs(delta) > 1f) listState.dispatchRawDelta(delta)
            lockedTop = null
            cardTop = nextTop
        }
        .then(if (embedded) Modifier else Modifier.padding(horizontal = 4.dp))

    Column(
        modifier = cardModifier,
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = 34.dp)
                .clip(RoundedCornerShape(8.dp))
                .background(collapsedSurface)
                .then(if (expandable) Modifier.noRippleClickable { toggleExpanded() } else Modifier)
                .padding(horizontal = 6.dp, vertical = 6.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (expandable) {
                if (expanded) {
                    ChevronDownGlyph(muted)
                } else {
                    ChevronRightGlyph(muted)
                }
            } else {
                Spacer(Modifier.width(18.dp))
            }
            ToolActivityIcon(kind = message.kind, darkMode = darkMode, expanded = false, sizeDp = 16)
            if (message.kind != TimelineMessageKind.ToolCall) {
                Text(
                    text = message.title,
                    color = muted,
                    fontSize = 13.sp,
                    fontWeight = FontWeight.Bold,
                    maxLines = 1,
                )
            }
            Text(
                text = target,
                modifier = Modifier.weight(1f),
                color = primary,
                fontSize = if (message.kind == TimelineMessageKind.FileChange) 13.sp else 12.sp,
                fontWeight = FontWeight.Bold,
                fontFamily = if (message.kind == TimelineMessageKind.FileChange) FontFamily.SansSerif else FontFamily.Monospace,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            message.subagent?.let { SubagentProgressPill(progress = it, darkMode = darkMode) }
            CompactStatusPill(label = message.badge.ifBlank { message.status }, darkMode = darkMode)
        }
        if (expanded && expandable) {
            if (message.kind != TimelineMessageKind.ToolCall || message.hasToolCallDetail) {
                val copyText = listOf(message.detail, message.body).filter { it.isNotBlank() }.joinToString("\n")
                val clipboard = LocalClipboardManager.current
                var copyDone by remember { mutableStateOf(false) }
                Box {
                    ToolActivityDetailCard(
                        message = message,
                        darkMode = darkMode,
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(14.dp))
                            .background(surface)
                            .border(1.dp, border, RoundedCornerShape(14.dp)),
                    )
                    if (copyText.isNotBlank()) {
                        androidx.compose.material3.IconButton(
                            onClick = {
                                clipboard.setText(AnnotatedString(copyText))
                                copyDone = true
                            },
                            modifier = Modifier
                                .align(Alignment.TopEnd)
                                .padding(4.dp)
                                .size(28.dp)
                                .alpha(0.55f),
                        ) {
                            androidx.compose.material3.Icon(
                                imageVector = Lucide.Copy,
                                contentDescription = "Copy",
                                tint = if (darkMode) Color(0xFFA1A1AA) else Color(0xFF7C7B76),
                                modifier = Modifier.size(14.dp),
                            )
                        }
                    }
                }
            }
            if (hasChildren) {
                SubagentChildren(
                    children = children,
                    darkMode = darkMode,
                    listState = listState,
                    onOpenFile = onOpenFile,
                )
            }
        }
    }
}

@Composable
private fun SubagentChildren(
    children: List<TimelineMessage>,
    darkMode: Boolean,
    listState: LazyListState,
    onOpenFile: (String) -> Unit,
    onCopyMessage: ((String) -> Unit)? = null,
) {
    val rail = if (darkMode) Color(0xFF3F3F46) else Color(0xFFD8D5CE)
    Row(modifier = Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
        Box(
            modifier = Modifier
                .padding(start = 7.dp, end = 4.dp)
                .width(2.dp)
                .fillMaxHeight()
                .clip(RoundedCornerShape(1.dp))
                .background(rail),
        )
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(7.dp),
        ) {
            children.forEach { child ->
                when (child.kind) {
                    TimelineMessageKind.Reasoning -> ReasoningSection(child, darkMode)
                    TimelineMessageKind.Command,
                    TimelineMessageKind.FileChange,
                    TimelineMessageKind.ToolCall -> ToolActivityCard(
                        message = child,
                        darkMode = darkMode,
                        listState = listState,
                        embedded = true,
                        onOpenFile = onOpenFile,
                    )
                    TimelineMessageKind.Notification -> NotificationCard(child, darkMode, onCopyMessage)
                    TimelineMessageKind.System -> ToolPlaceholder(child, darkMode)
                    TimelineMessageKind.Compact -> CompactSeparator(child, darkMode)
                    TimelineMessageKind.SkillListing -> SkillListingCard(child, darkMode)
                    TimelineMessageKind.DeferredToolsDelta -> DeferredToolsDeltaPill(child, darkMode)
                    TimelineMessageKind.InvokedSkills -> InvokedSkillsPill(child, darkMode)
                    TimelineMessageKind.Text -> when (child.author) {
                        MessageAuthor.Agent -> AgentMarkdownText(child.text, darkMode, onOpenFile = onOpenFile)
                        else -> AgentMarkdownText(child.text, darkMode, onOpenFile = onOpenFile)
                    }
                }
            }
        }
    }
}

@Composable
private fun ToolActivityDetailCard(
    message: TimelineMessage,
    darkMode: Boolean,
    modifier: Modifier = Modifier,
) {
    val muted = if (darkMode) Color(0xFFA1A1AA) else Color(0xFF7C7B76)

    Column(
        modifier = modifier.padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (message.kind == TimelineMessageKind.FileChange && message.detail.isNotBlank()) {
            Text(
                text = message.detail,
                color = muted,
                fontSize = 12.sp,
                lineHeight = 17.sp,
                fontWeight = FontWeight.Medium,
                fontFamily = FontFamily.Monospace,
            )
        }
        when (message.kind) {
            TimelineMessageKind.Command -> {
                CommandPreview(command = message.detail.ifBlank { message.subtitle }, output = message.body, darkMode = darkMode)
            }
            TimelineMessageKind.FileChange -> {
                DiffPreview(diff = message.body, path = message.detail.ifBlank { message.subtitle }, darkMode = darkMode)
            }
            TimelineMessageKind.ToolCall -> {
                ToolCallPreview(message = message, darkMode = darkMode)
            }
            else -> Unit
        }
    }
}

private fun TimelineMessage.toolSummaryTarget(): String {
    return if (kind == TimelineMessageKind.ToolCall) {
        title.ifBlank { text }
    } else {
        subtitle.ifBlank { text }.ifBlank { title }
    }
}

@Composable
private fun ToolCallPreview(message: TimelineMessage, darkMode: Boolean) {
    // When detail is populated it means this is an MCP tool call with structured
    // arguments/result — render with McpToolPreview for clear separation.
    if (message.detail.isNotBlank()) {
        McpToolPreview(
            arguments = message.detail,
            output = message.body,
            isError = message.body.startsWith("Error:"),
            darkMode = darkMode,
        )
        return
    }
    val details = listOf(
        message.subtitle,
        message.detail,
        message.body,
    ).filter { it.isNotBlank() }
    if (details.isEmpty()) return
    CommandPreviewSection(
        label = message.title.ifBlank { message.text.ifBlank { "tool" } },
        text = details.joinToString("\n"),
        languageHint = null,
        darkMode = darkMode,
    )
}

@Composable
private fun McpToolPreview(arguments: String, output: String, isError: Boolean, darkMode: Boolean) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (arguments.isNotBlank()) {
            CommandPreviewSection(
                label = stringResource(R.string.session_mcp_arguments),
                text = arguments,
                languageHint = "json",
                darkMode = darkMode,
            )
        }
        if (output.isNotBlank()) {
            val cleanOutput = if (isError) output.removePrefix("Error: ") else output
            CommandPreviewSection(
                label = if (isError) stringResource(R.string.session_mcp_error) else stringResource(R.string.session_mcp_result),
                text = cleanOutput,
                languageHint = null,
                darkMode = darkMode,
            )
        }
    }
}

private val TimelineMessage.hasToolCallDetail: Boolean
    get() = subtitle.isNotBlank() || detail.isNotBlank() || body.isNotBlank()

@Composable
private fun CommandPreview(command: String, output: String, darkMode: Boolean) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        CommandLineBar(command = command.ifBlank { stringResource(R.string.session_command_fallback) }, darkMode = darkMode)
        CommandPreviewSection(
            label = stringResource(R.string.session_output),
            text = output.ifBlank { stringResource(R.string.session_no_output) },
            languageHint = null,
            darkMode = darkMode,
        )
    }
}

@Composable
private fun CommandLineBar(command: String, darkMode: Boolean) {
    val muted = if (darkMode) Color(0xFFA1A1AA) else Color(0xFF7C7B76)
    val text = if (darkMode) Color(0xFFE4E4E7) else Color(0xFF2B2C29)
    val surface = if (darkMode) Color(0xFF111113) else Color.White.copy(alpha = 0.72f)
    val border = if (darkMode) Color(0xFF27272A) else Color(0xFFE0DED8)
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(
            text = stringResource(R.string.session_command),
            color = muted,
            fontSize = 11.sp,
            fontWeight = FontWeight.Bold,
            maxLines = 1,
        )
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(14.dp))
                .background(surface)
                .border(1.dp, border, RoundedCornerShape(14.dp))
                .padding(horizontal = 10.dp, vertical = 9.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.Top,
        ) {
            Text(
                text = "$",
                color = muted,
                fontSize = 13.sp,
                lineHeight = 18.sp,
                fontWeight = FontWeight.ExtraBold,
                fontFamily = FontFamily.Monospace,
            )
            Text(
                text = command,
                color = text,
                fontSize = 13.sp,
                lineHeight = 18.sp,
                fontWeight = FontWeight.SemiBold,
                fontFamily = FontFamily.Monospace,
                maxLines = 3,
                overflow = TextOverflow.Ellipsis,
                style = TextStyle(letterSpacing = 0.sp),
                modifier = Modifier.weight(1f),
            )
        }
    }
}

@Composable
private fun CommandPreviewSection(
    label: String,
    text: String,
    languageHint: String?,
    darkMode: Boolean,
) {
    val muted = if (darkMode) Color(0xFFA1A1AA) else Color(0xFF7C7B76)
    val lineCount = text.count { it == '\n' } + 1
    val collapsible = lineCount > 25
    var expanded by remember(text) { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = label,
                color = muted,
                fontSize = 11.sp,
                fontWeight = FontWeight.Bold,
                maxLines = 1,
            )
            if (collapsible) {
                androidx.compose.material3.TextButton(
                    onClick = { expanded = !expanded },
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 6.dp, vertical = 0.dp),
                    modifier = Modifier.height(20.dp),
                ) {
                    Text(
                        text = if (expanded) "Collapse" else "Show all $lineCount lines",
                        color = muted,
                        fontSize = 10.sp,
                        fontWeight = FontWeight.Medium,
                    )
                }
            }
        }
        SoraCodeBlock(
            text = text,
            languageHint = languageHint,
            darkMode = darkMode,
            fixedHeight = if (collapsible && !expanded) 360.dp else null,
        )
    }
}

@Composable
private fun DiffPreview(diff: String, path: String, darkMode: Boolean) {
    val preview = remember(diff) { diffPreview(diff) }
    SoraCodeBlock(
        text = preview.text.ifBlank { stringResource(R.string.session_no_preview) },
        languageHint = path,
        darkMode = darkMode,
        diffHighlights = preview.highlights,
    )
}

@Composable
private fun ToolActivityIcon(
    kind: TimelineMessageKind,
    darkMode: Boolean,
    expanded: Boolean,
    sizeDp: Int = 20,
) {
    when (kind) {
        TimelineMessageKind.Command -> PngToolIcon(
            lightRes = if (expanded) R.drawable.ic_ran_expanded_light else R.drawable.ic_terminal_command_light,
            darkRes = if (expanded) R.drawable.ic_ran_expanded_dark else R.drawable.ic_terminal_command_dark,
            darkMode = darkMode,
            sizeDp = sizeDp,
        )
        TimelineMessageKind.FileChange -> PngToolIcon(
            lightRes = if (expanded) R.drawable.ic_edited_expanded_light else R.drawable.ic_edited_file_light,
            darkRes = if (expanded) R.drawable.ic_edited_expanded_dark else R.drawable.ic_edited_file_dark,
            darkMode = darkMode,
            sizeDp = sizeDp,
        )
        else -> PngToolIcon(
            lightRes = R.drawable.ic_tool_call_light,
            darkRes = R.drawable.ic_tool_call_dark,
            darkMode = darkMode,
            sizeDp = sizeDp,
        )
    }
}

@Composable
private fun PngToolIcon(
    lightRes: Int,
    darkRes: Int,
    darkMode: Boolean,
    sizeDp: Int = 20,
) {
    Image(
        painter = painterResource(if (darkMode) darkRes else lightRes),
        contentDescription = null,
        modifier = Modifier.size(sizeDp.dp),
    )
}

@Composable
private fun CompactStatusPill(label: String, darkMode: Boolean) {
    Row(
        modifier = Modifier
            .height(20.dp)
            .widthIn(min = 40.dp)
            .clip(CircleShape)
            .background(if (darkMode) Color(0xFF27272A) else Color(0xFFE4E2DD))
            .padding(horizontal = 8.dp),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = label,
            color = if (darkMode) Color(0xFFD4D4D8) else Color(0xFF6F6E69),
            fontSize = 11.sp,
            lineHeight = 11.sp,
            fontWeight = FontWeight.Bold,
            maxLines = 1,
        )
    }
}

// Compact sub-agent progress pill shown on the parent Agent tool card header.
// While running it shows a "Sub-agent running" hint; once finished it collapses
// to the token/duration usage summary the connector folded in.
@Composable
private fun SubagentProgressPill(progress: SubagentProgress, darkMode: Boolean) {
    val label = if (progress.finished) {
        val parts = mutableListOf<String>()
        if (progress.totalTokens > 0) {
            parts += stringResource(R.string.session_subagent_tokens, formatCompactCount(progress.totalTokens))
        }
        if (progress.durationMs > 0) {
            val seconds = (progress.durationMs / 100L) / 10.0
            parts += stringResource(R.string.session_subagent_duration, formatSeconds(seconds))
        }
        parts.joinToString(" · ").ifBlank { progress.status }
    } else {
        stringResource(R.string.session_subagent_running)
    }
    if (label.isBlank()) return
    Row(
        modifier = Modifier
            .height(20.dp)
            .clip(CircleShape)
            .background(if (darkMode) Color(0xFF1E3A34) else Color(0xFFDCEFE7))
            .padding(horizontal = 8.dp),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = label,
            color = if (darkMode) Color(0xFF7DD3B0) else Color(0xFF2F7A5E),
            fontSize = 11.sp,
            lineHeight = 11.sp,
            fontWeight = FontWeight.Bold,
            maxLines = 1,
        )
    }
}

private fun formatCompactCount(value: Long): String {
    return when {
        value >= 1_000_000 -> "${(value / 100_000L) / 10.0}M"
        value >= 1_000 -> "${(value / 100L) / 10.0}k"
        else -> value.toString()
    }
}

private fun formatSeconds(seconds: Double): String {
    return if (seconds % 1.0 == 0.0) seconds.toLong().toString() else seconds.toString()
}

@Composable
private fun ToolPlaceholder(message: TimelineMessage, darkMode: Boolean) {
    Row(
        modifier = Modifier.padding(horizontal = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        SparklesGlyph(if (darkMode) Color(0xFFA1A1AA) else Color(0xFF7C7B76))
        Text(
            text = message.text.ifBlank { message.type },
            color = if (darkMode) Color(0xFFA1A1AA) else Color(0xFF7C7B76),
            fontSize = 13.sp,
            fontWeight = FontWeight.Bold,
        )
    }
}

@Composable
private fun SkillListingCard(message: TimelineMessage, darkMode: Boolean) {
    if (message.skills.isEmpty()) return
    var expanded by remember { mutableStateOf(false) }
    val pillColor = if (darkMode) Color(0xFF3F3F46) else Color(0xFFE4E4E7)
    val textColor = if (darkMode) Color(0xFFD4D4D8) else Color(0xFF52525B)
    val mutedColor = if (darkMode) Color(0xFFA1A1AA) else Color(0xFF71717A)
    Column {
        Row(
            modifier = Modifier
                .noRippleClickable { expanded = !expanded }
                .background(color = pillColor, shape = androidx.compose.foundation.shape.RoundedCornerShape(50))
                .padding(horizontal = 10.dp, vertical = 4.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            androidx.compose.material3.Icon(
                imageVector = if (expanded) Lucide.ChevronDown else Lucide.ChevronRight,
                contentDescription = null,
                tint = textColor,
                modifier = Modifier.size(14.dp),
            )
            Text(
                text = "${message.skills.size} skills available",
                color = textColor,
                fontSize = 12.sp,
                fontWeight = FontWeight.Medium,
            )
        }
        if (expanded) {
            Column(modifier = Modifier.padding(start = 4.dp, top = 4.dp)) {
                message.skills.forEach { skill ->
                    Row(
                        modifier = Modifier.padding(vertical = 1.dp),
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        Text(
                            text = skill.name,
                            color = if (darkMode) Color(0xFFD4D4D8) else Color(0xFF27272A),
                            fontSize = 12.sp,
                            fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace,
                            fontWeight = FontWeight.Medium,
                            modifier = Modifier.widthIn(max = 120.dp),
                            maxLines = 1,
                            overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                        )
                        if (skill.description.isNotBlank()) {
                            Text(
                                text = skill.description,
                                color = mutedColor,
                                fontSize = 12.sp,
                                maxLines = 1,
                                overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun DeferredToolsDeltaPill(message: TimelineMessage, darkMode: Boolean) {
    val parts = buildList {
        if (message.addedToolNames.isNotEmpty()) add("+${message.addedToolNames.size} deferred tools")
        if (message.removedToolNames.isNotEmpty()) add("-${message.removedToolNames.size} tools")
    }
    if (parts.isEmpty()) return
    val pillColor = if (darkMode) Color(0xFF3F3F46) else Color(0xFFE4E4E7)
    val textColor = if (darkMode) Color(0xFFD4D4D8) else Color(0xFF52525B)
    Row(
        modifier = Modifier
            .background(color = pillColor, shape = androidx.compose.foundation.shape.RoundedCornerShape(50))
            .padding(horizontal = 10.dp, vertical = 3.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = parts.joinToString(", "),
            color = textColor,
            fontSize = 12.sp,
            fontWeight = FontWeight.Medium,
        )
    }
}

@Composable
private fun InvokedSkillsPill(message: TimelineMessage, darkMode: Boolean) {
    if (message.skills.isEmpty()) return
    val names = message.skills.joinToString(", ") { it.name }
    val pillColor = if (darkMode) Color(0xFF3F3F46) else Color(0xFFE4E4E7)
    val textColor = if (darkMode) Color(0xFFD4D4D8) else Color(0xFF52525B)
    Row(
        modifier = Modifier
            .background(color = pillColor, shape = androidx.compose.foundation.shape.RoundedCornerShape(50))
            .padding(horizontal = 10.dp, vertical = 3.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = "Skills: $names",
            color = textColor,
            fontSize = 12.sp,
            fontWeight = FontWeight.Medium,
            maxLines = 1,
            overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
        )
    }
}

@Composable
internal fun EmptyDetailMessage(message: String) {
    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = message,
            color = LocalAAColors.current.muted,
            fontSize = 14.sp,
            fontWeight = FontWeight.Medium,
        )
    }
}

@Composable
internal fun SessionDetailErrorState(
    message: String,
    darkMode: Boolean,
    onRetry: () -> Unit,
) {
    val muted = if (darkMode) Color(0xFFA1A1AA) else Color(0xFF7C7B76)
    val accent = if (darkMode) Color(0xFFE4E4E7) else Color(0xFF2B2C29)
    val border = if (darkMode) Color(0xFF3F3F46) else Color(0xFFE0DED8)
    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(14.dp),
            modifier = Modifier.padding(horizontal = 32.dp),
        ) {
            Text(
                text = message.ifBlank { stringResource(R.string.session_load_failed) },
                color = muted,
                fontSize = 14.sp,
                fontWeight = FontWeight.Medium,
                textAlign = TextAlign.Center,
            )
            Row(
                modifier = Modifier
                    .clip(RoundedCornerShape(999.dp))
                    .border(1.dp, border, RoundedCornerShape(999.dp))
                    .noRippleClickable(onClick = onRetry)
                    .padding(horizontal = 18.dp, vertical = 9.dp),
                horizontalArrangement = Arrangement.spacedBy(7.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                androidx.compose.material3.Icon(
                    imageVector = Lucide.RefreshCw,
                    contentDescription = null,
                    tint = accent,
                    modifier = Modifier.size(15.dp),
                )
                Text(
                    text = stringResource(R.string.session_retry),
                    color = accent,
                    fontSize = 13.sp,
                    fontWeight = FontWeight.SemiBold,
                )
            }
        }
    }
}

@Composable
internal fun SessionWelcomeMessage(darkMode: Boolean) {
    val titles = listOf(
        stringResource(R.string.session_welcome_1),
        stringResource(R.string.session_welcome_2),
        stringResource(R.string.session_welcome_3),
        stringResource(R.string.session_welcome_4),
        stringResource(R.string.session_welcome_5),
        stringResource(R.string.session_welcome_6),
        stringResource(R.string.session_welcome_7),
        stringResource(R.string.session_welcome_8),
        stringResource(R.string.session_welcome_9),
        stringResource(R.string.session_welcome_10),
        stringResource(R.string.session_welcome_11),
        stringResource(R.string.session_welcome_12),
        stringResource(R.string.session_welcome_13),
        stringResource(R.string.session_welcome_14),
        stringResource(R.string.session_welcome_15),
        stringResource(R.string.session_welcome_16),
    )
    var titleIndex by remember { mutableStateOf(0) }
    var typedTitle by remember { mutableStateOf("") }

    LaunchedEffect(titleIndex, titles) {
        val title = titles[titleIndex % titles.size]
        for (count in 0..title.length) {
            typedTitle = title.take(count)
            if (count < title.length) delay(SESSION_WELCOME_WRITE_MS)
        }
        delay(SESSION_WELCOME_HOLD_MS)
        for (count in title.length downTo 0) {
            typedTitle = title.take(count)
            if (count > 0) delay(SESSION_WELCOME_ERASE_MS)
        }
        titleIndex = (titleIndex + 1) % titles.size
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 30.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = typedTitle,
            color = if (darkMode) Color(0xFFFAFAFA) else Color(0xFF3E403A),
            fontSize = 32.sp,
            fontWeight = FontWeight(650),
            fontFamily = SessionWelcomeFontFamily,
            lineHeight = 34.sp,
            textAlign = TextAlign.Center,
            modifier = Modifier.width(310.dp),
        )
    }
}
