package com.agentsanywhere.app.ui.screens.devices

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.agentsanywhere.app.R
import com.agentsanywhere.app.api.McpServerConfig
import com.agentsanywhere.app.api.McpServerDraft
import com.agentsanywhere.app.api.McpServerType
import com.agentsanywhere.app.api.toDraftList
import com.agentsanywhere.app.api.toMcpServersMap
import com.agentsanywhere.app.ui.designsystem.LocalAAColors
import com.agentsanywhere.app.ui.designsystem.noRippleClickable
import com.composables.icons.lucide.Lucide
import com.composables.icons.lucide.Plus
import com.composables.icons.lucide.Trash2
import com.composables.icons.lucide.X
import kotlinx.coroutines.launch

private sealed class McpLoadState {
    object Loading : McpLoadState()
    object Error : McpLoadState()
    object Content : McpLoadState()
}

private data class McpPalette(
    val sheet: Color,
    val handle: Color,
    val title: Color,
    val text: Color,
    val hint: Color,
    val border: Color,
    val cardBg: Color,
    val selectedSegment: Color,
    val selectedSegmentText: Color,
    val unselectedSegmentText: Color,
    val destructive: Color,
    val buttonBg: Color,
    val buttonText: Color,
    val errorSurface: Color,
    val errorBorder: Color,
    val errorText: Color,
)

private fun mcpPalette(darkMode: Boolean): McpPalette = if (darkMode) {
    McpPalette(
        sheet = Color(0xFF18181B),
        handle = Color(0xFF3F3F46),
        title = Color(0xFFFAFAFA),
        text = Color(0xFFA1A1AA),
        hint = Color(0xFF52525B),
        border = Color(0xFF27272A),
        cardBg = Color(0xFF27272A),
        selectedSegment = Color(0xFF3F3F46),
        selectedSegmentText = Color(0xFFFAFAFA),
        unselectedSegmentText = Color(0xFF71717A),
        destructive = Color(0xFFEF4444),
        buttonBg = Color(0xFF3F3F46),
        buttonText = Color(0xFFFAFAFA),
        errorSurface = Color(0xFF2A1418),
        errorBorder = Color(0xFF4A1C24),
        errorText = Color(0xFFF87171),
    )
} else {
    McpPalette(
        sheet = Color(0xFFFFFEFC),
        handle = Color(0xFFE4E4E7),
        title = Color(0xFF09090B),
        text = Color(0xFF3F3F46),
        hint = Color(0xFFA1A1AA),
        border = Color(0xFFE4E4E7),
        cardBg = Color(0xFFF4F4F5),
        selectedSegment = Color(0xFFFFFFFF),
        selectedSegmentText = Color(0xFF09090B),
        unselectedSegmentText = Color(0xFF71717A),
        destructive = Color(0xFFDC2626),
        buttonBg = Color(0xFF18181B),
        buttonText = Color(0xFFFAFAFA),
        errorSurface = Color(0xFFFEF2F2),
        errorBorder = Color(0xFFFECACA),
        errorText = Color(0xFFDC2626),
    )
}

private fun validateDrafts(drafts: List<McpServerDraft>): String? {
    val names = drafts.map { it.name.trim() }
    if (names.any { it.isEmpty() }) return "name_required"
    if (names.size != names.toSet().size) return "name_unique"
    for (d in drafts) {
        if (d.type == McpServerType.stdio && d.command.isBlank()) return "command_required"
        if ((d.type == McpServerType.http || d.type == McpServerType.sse) && d.url.isBlank()) return "url_required"
    }
    return null
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ConnectorMcpServersSheet(
    connectorId: String,
    onDismiss: () -> Unit,
    onLoadMcpServers: suspend () -> Result<Map<String, McpServerConfig>>,
    onSaveMcpServers: suspend (Map<String, McpServerConfig>) -> Result<Map<String, McpServerConfig>>,
) {
    val colors = LocalAAColors.current
    val darkMode = colors.canvas == Color(0xFF09090B)
    val palette = mcpPalette(darkMode)
    val bodyMaxHeight = (LocalConfiguration.current.screenHeightDp * 0.65f).dp
    val scope = rememberCoroutineScope()
    val scrollState = rememberScrollState()

    var loadState by remember { mutableStateOf<McpLoadState>(McpLoadState.Loading) }
    var drafts by remember { mutableStateOf(listOf<McpServerDraft>()) }
    var saving by remember { mutableStateOf(false) }
    var saveError by remember { mutableStateOf<String?>(null) }
    var validationError by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(connectorId) {
        loadState = McpLoadState.Loading
        onLoadMcpServers()
            .onSuccess { map ->
                drafts = map.toDraftList()
                loadState = McpLoadState.Content
            }
            .onFailure { loadState = McpLoadState.Error }
    }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        shape = RoundedCornerShape(topStart = 28.dp, topEnd = 28.dp),
        containerColor = palette.sheet,
        contentColor = palette.title,
        dragHandle = null,
        scrimColor = if (darkMode) Color(0x99000000) else Color(0x66000000),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .navigationBarsPadding()
                .padding(start = 22.dp, end = 22.dp, top = 10.dp, bottom = 20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            // Handle
            Box(
                modifier = Modifier.fillMaxWidth().height(12.dp),
                contentAlignment = Alignment.Center,
            ) {
                Box(
                    modifier = Modifier
                        .size(width = 42.dp, height = 5.dp)
                        .clip(RoundedCornerShape(50))
                        .background(palette.handle),
                )
            }

            // Header
            Row(
                modifier = Modifier.fillMaxWidth().height(44.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Text(
                    text = stringResource(R.string.connector_mcp_title),
                    color = palette.title,
                    fontSize = 20.sp,
                    fontWeight = FontWeight.ExtraBold,
                    modifier = Modifier.weight(1f),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                RoundIconAction(
                    icon = Lucide.X,
                    contentDescription = stringResource(R.string.common_close),
                    danger = false,
                    onClick = onDismiss,
                )
            }

            when (loadState) {
                is McpLoadState.Loading -> {
                    Box(
                        modifier = Modifier.fillMaxWidth().height(160.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(24.dp),
                            strokeWidth = 2.dp,
                            color = palette.text,
                        )
                    }
                }
                is McpLoadState.Error -> {
                    Box(
                        modifier = Modifier.fillMaxWidth().height(120.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            text = stringResource(R.string.connector_mcp_load_failed),
                            color = palette.errorText,
                            fontSize = 14.sp,
                        )
                    }
                }
                is McpLoadState.Content -> {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(max = bodyMaxHeight)
                            .verticalScroll(scrollState),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        if (drafts.isEmpty()) {
                            Text(
                                text = stringResource(R.string.connector_mcp_no_servers),
                                color = palette.hint,
                                fontSize = 14.sp,
                            )
                        } else {
                            drafts.forEach { draft ->
                                McpServerCard(
                                    draft = draft,
                                    palette = palette,
                                    onUpdate = { updated ->
                                        drafts = drafts.map { if (it.id == updated.id) updated else it }
                                        validationError = null
                                    },
                                    onDelete = {
                                        drafts = drafts.filter { it.id != draft.id }
                                        validationError = null
                                    },
                                )
                            }
                        }

                        // Add server button
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(8.dp))
                                .border(1.dp, palette.border, RoundedCornerShape(8.dp))
                                .noRippleClickable {
                                    drafts = drafts + McpServerDraft()
                                    validationError = null
                                }
                                .padding(horizontal = 12.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            androidx.compose.material3.Icon(
                                imageVector = Lucide.Plus,
                                contentDescription = null,
                                tint = palette.hint,
                                modifier = Modifier.size(14.dp),
                            )
                            Text(
                                text = stringResource(R.string.connector_mcp_add_server),
                                color = palette.hint,
                                fontSize = 13.sp,
                            )
                        }
                    }

                    // Validation / save error
                    if (validationError != null || saveError != null) {
                        Text(
                            text = validationError ?: saveError ?: "",
                            color = palette.errorText,
                            fontSize = 12.sp,
                        )
                    }

                    // Save button
                    val savingLabel = stringResource(R.string.common_working)
                    val saveLabel = stringResource(R.string.common_save)
                    val errNameRequired = stringResource(R.string.connector_mcp_name_required)
                    val errNameUnique = stringResource(R.string.connector_mcp_name_unique)
                    val errCommandRequired = stringResource(R.string.connector_mcp_command_required)
                    val errUrlRequired = stringResource(R.string.connector_mcp_url_required)
                    val errSaveFailed = stringResource(R.string.connector_mcp_save_failed)
                    SheetTextButton(
                        label = if (saving) savingLabel else saveLabel,
                        primary = true,
                        enabled = !saving,
                        modifier = Modifier.fillMaxWidth(),
                        onClick = {
                            val err = validateDrafts(drafts)
                            if (err != null) {
                                validationError = when (err) {
                                    "name_required" -> errNameRequired
                                    "name_unique" -> errNameUnique
                                    "command_required" -> errCommandRequired
                                    else -> errUrlRequired
                                }
                                return@SheetTextButton
                            }
                            validationError = null
                            saving = true
                            saveError = null
                            scope.launch {
                                onSaveMcpServers(drafts.toMcpServersMap())
                                    .onSuccess { map ->
                                        drafts = map.toDraftList()
                                        onDismiss()
                                    }
                                    .onFailure {
                                        saveError = errSaveFailed
                                    }
                                saving = false
                            }
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun McpServerCard(
    draft: McpServerDraft,
    palette: McpPalette,
    onUpdate: (McpServerDraft) -> Unit,
    onDelete: () -> Unit,
) {
    val fieldColors = OutlinedTextFieldDefaults.colors(
        focusedBorderColor = palette.border,
        unfocusedBorderColor = palette.border,
        focusedTextColor = palette.title,
        unfocusedTextColor = palette.title,
        focusedPlaceholderColor = palette.hint,
        unfocusedPlaceholderColor = palette.hint,
        cursorColor = palette.title,
    )

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(10.dp))
            .background(palette.cardBg)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        // Name + delete
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            OutlinedTextField(
                value = draft.name,
                onValueChange = { onUpdate(draft.copy(name = it)) },
                modifier = Modifier.weight(1f),
                placeholder = { Text(stringResource(R.string.connector_mcp_server_name), fontSize = 13.sp) },
                colors = fieldColors,
                singleLine = true,
                textStyle = androidx.compose.ui.text.TextStyle(fontSize = 13.sp, fontWeight = FontWeight.Medium),
            )
            Box(
                modifier = Modifier
                    .size(36.dp)
                    .clip(RoundedCornerShape(8.dp))
                    .background(Color(0x22EF4444))
                    .noRippleClickable { onDelete() },
                contentAlignment = Alignment.Center,
            ) {
                androidx.compose.material3.Icon(
                    imageVector = Lucide.Trash2,
                    contentDescription = stringResource(R.string.common_delete),
                    tint = palette.destructive,
                    modifier = Modifier.size(14.dp),
                )
            }
        }

        // Type selector
        val types = McpServerType.values()
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            types.forEach { tp ->
                val selected = draft.type == tp
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(6.dp))
                        .background(if (selected) palette.selectedSegment else Color.Transparent)
                        .border(1.dp, palette.border, RoundedCornerShape(6.dp))
                        .noRippleClickable { onUpdate(draft.copy(type = tp)) }
                        .padding(horizontal = 12.dp, vertical = 5.dp),
                ) {
                    Text(
                        text = tp.name,
                        color = if (selected) palette.selectedSegmentText else palette.unselectedSegmentText,
                        fontSize = 12.sp,
                        fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
                    )
                }
            }
        }

        // Conditional fields
        if (draft.type == McpServerType.stdio) {
            OutlinedTextField(
                value = draft.command,
                onValueChange = { onUpdate(draft.copy(command = it)) },
                modifier = Modifier.fillMaxWidth(),
                placeholder = { Text(stringResource(R.string.connector_mcp_command), fontSize = 13.sp) },
                colors = fieldColors,
                singleLine = true,
                textStyle = androidx.compose.ui.text.TextStyle(fontSize = 13.sp),
            )
            OutlinedTextField(
                value = draft.argsText,
                onValueChange = { onUpdate(draft.copy(argsText = it)) },
                modifier = Modifier.fillMaxWidth(),
                placeholder = { Text(stringResource(R.string.connector_mcp_args), fontSize = 13.sp) },
                colors = fieldColors,
                minLines = 2,
                maxLines = 4,
                textStyle = androidx.compose.ui.text.TextStyle(fontSize = 12.sp),
            )
            KVSection(
                label = stringResource(R.string.connector_mcp_env),
                addLabel = stringResource(R.string.connector_mcp_add_env),
                pairs = draft.env,
                palette = palette,
                onChange = { onUpdate(draft.copy(env = it)) },
            )
        } else {
            OutlinedTextField(
                value = draft.url,
                onValueChange = { onUpdate(draft.copy(url = it)) },
                modifier = Modifier.fillMaxWidth(),
                placeholder = { Text(stringResource(R.string.connector_mcp_url), fontSize = 13.sp) },
                colors = fieldColors,
                singleLine = true,
                textStyle = androidx.compose.ui.text.TextStyle(fontSize = 13.sp),
            )
            KVSection(
                label = stringResource(R.string.connector_mcp_headers),
                addLabel = stringResource(R.string.connector_mcp_add_header),
                pairs = draft.headers,
                palette = palette,
                onChange = { onUpdate(draft.copy(headers = it)) },
            )
        }
    }
}

@Composable
private fun KVSection(
    label: String,
    addLabel: String,
    pairs: List<Pair<String, String>>,
    palette: McpPalette,
    onChange: (List<Pair<String, String>>) -> Unit,
) {
    val fieldColors = OutlinedTextFieldDefaults.colors(
        focusedBorderColor = palette.border,
        unfocusedBorderColor = palette.border,
        focusedTextColor = palette.title,
        unfocusedTextColor = palette.title,
        focusedPlaceholderColor = palette.hint,
        unfocusedPlaceholderColor = palette.hint,
        cursorColor = palette.title,
    )
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(label, color = palette.hint, fontSize = 11.sp, fontWeight = FontWeight.SemiBold)
        pairs.forEachIndexed { i, (k, v) ->
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                OutlinedTextField(
                    value = k,
                    onValueChange = { newK -> onChange(pairs.mapIndexed { j, p -> if (j == i) newK to p.second else p }) },
                    modifier = Modifier.weight(1f),
                    placeholder = { Text("KEY", fontSize = 11.sp) },
                    colors = fieldColors,
                    singleLine = true,
                    textStyle = androidx.compose.ui.text.TextStyle(fontSize = 11.sp),
                )
                Text("=", color = palette.hint, fontSize = 11.sp)
                OutlinedTextField(
                    value = v,
                    onValueChange = { newV -> onChange(pairs.mapIndexed { j, p -> if (j == i) p.first to newV else p }) },
                    modifier = Modifier.weight(1f),
                    placeholder = { Text("value", fontSize = 11.sp) },
                    colors = fieldColors,
                    singleLine = true,
                    textStyle = androidx.compose.ui.text.TextStyle(fontSize = 11.sp),
                )
                Box(
                    modifier = Modifier
                        .size(28.dp)
                        .clip(RoundedCornerShape(6.dp))
                        .noRippleClickable { onChange(pairs.filterIndexed { j, _ -> j != i }) },
                    contentAlignment = Alignment.Center,
                ) {
                    androidx.compose.material3.Icon(
                        imageVector = Lucide.X,
                        contentDescription = null,
                        tint = palette.hint,
                        modifier = Modifier.size(12.dp),
                    )
                }
            }
        }
        Row(
            modifier = Modifier
                .noRippleClickable { onChange(pairs + ("" to "")) }
                .padding(vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            androidx.compose.material3.Icon(
                imageVector = Lucide.Plus,
                contentDescription = null,
                tint = palette.hint,
                modifier = Modifier.size(12.dp),
            )
            Text(addLabel, color = palette.hint, fontSize = 12.sp)
        }
    }
}
