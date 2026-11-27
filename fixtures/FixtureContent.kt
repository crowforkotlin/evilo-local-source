package crow.evilo.plugin.template

import crow.evilo.model.MediaChapter
import crow.evilo.model.MediaContent
import crow.evilo.model.MediaId
import crow.evilo.model.MediaItem
import crow.evilo.model.MediaKind
import crow.evilo.model.Page
import crow.evilo.plugin.api.PluginDescriptor
import crow.evilo.plugin.api.PluginOperation
import crow.evilo.plugin.api.PluginOperationKind
import crow.evilo.plugin.api.PluginResult
import kotlinx.serialization.Serializable

@Serializable
data class FixtureChapter(val id: String, val title: String, val pages: List<String>)

@Serializable
data class FixtureWork(
    val id: String,
    val title: String,
    val author: String,
    val description: String,
    val cover: String,
    val tags: List<String>,
    val chapters: List<FixtureChapter>,
)

@Serializable
data class FixtureData(val baseUrl: String, val works: List<FixtureWork>)

/** All content is fixed at generation time. Operations never randomize or call the host. */
class TemplateContent(private val descriptor: PluginDescriptor, private val data: FixtureData) {
    private fun item(work: FixtureWork) = MediaItem(
        id = MediaId(descriptor.id, MediaKind.MANGA, work.id),
        title = work.title,
        url = "${data.baseUrl}/works/${work.id}/",
        coverUrl = "${data.baseUrl}/${work.cover}",
        description = work.description,
        authors = listOf(work.author),
        tags = work.tags,
        extensions = if (descriptor.configuration.groups.flatMap { it.fields }.any { it.localMetadataKey == "fixture.parity" })
            mapOf("fixture.parity" to if (data.works.indexOf(work) % 2 == 0) "even" else "odd") else emptyMap(),
    )

    fun execute(operation: PluginOperation): PluginResult {
        require(operation.kind == MediaKind.MANGA && operation.page > 0)
        operation.item?.let { require(it.id.pluginId == descriptor.id && it.id.kind == MediaKind.MANGA) }
        operation.chapter?.let { require(it.itemId.pluginId == descriptor.id && it.itemId.kind == MediaKind.MANGA) }
        val filters = crow.evilo.plugin.api.resolvePluginFilters(descriptor.configuration, operation.filters,
            crow.evilo.plugin.api.PluginFilterScope.PROVIDER)
        val access = descriptor.configuration.access.map { requirement ->
            crow.evilo.plugin.api.PluginAccessState(requirement.id, crow.evilo.plugin.api.PluginAccessStatus.UNSUPPORTED,
                actionId = requirement.actionId)
        }
        val result = when (operation.operation) {
            PluginOperationKind.SEARCH -> {
                val query = operation.query.trim()
                val matching = data.works.filterIndexed { index, work ->
                    val tags = filters["tags"]?.choiceIds.orEmpty()
                    filters["include-works"]?.toggle != false && work.title.contains(filters["title"]?.text.orEmpty(), true) &&
                        (tags.isEmpty() || (if (index % 2 == 0) "even" else "odd") in tags) &&
                        (query.isEmpty() || work.title.contains(query, true) || work.author.contains(query, true) ||
                            work.tags.any { it.contains(query, true) })
                }
                val limit = (filters["limit"]?.number?.toInt() ?: operation.extensions["limit"]?.toIntOrNull() ?: 12).coerceIn(1, 100)
                val offset = (operation.page.toLong() - 1) * limit
                val selected = if (offset >= matching.size) emptyList() else
                    matching.drop(offset.toInt()).take(limit).map(::item)
                PluginResult(items = selected, hasNextPage = offset + selected.size < matching.size)
            }
            PluginOperationKind.DETAILS -> {
                val selected = requireNotNull(operation.item)
                val work = data.works.single { it.id == selected.id.value }
                PluginResult(details = item(work))
            }
            PluginOperationKind.CHAPTERS -> {
                val selected = requireNotNull(operation.item)
                val work = data.works.single { it.id == selected.id.value }
                PluginResult(chapters = work.chapters.mapIndexed { index, chapter ->
                    MediaChapter(
                        itemId = selected.id,
                        id = chapter.id,
                        title = chapter.title,
                        url = "${data.baseUrl}/works/${work.id}/${chapter.id}/",
                        number = (index + 1).toDouble(),
                    )
                })
            }
            PluginOperationKind.CONTENT -> {
                val selected = requireNotNull(operation.chapter)
                operation.item?.let { require(it.id == selected.itemId) }
                val work = data.works.single { it.id == selected.itemId.value }
                val chapter = work.chapters.single { it.id == selected.id }
                PluginResult(content = MediaContent(images = chapter.pages.mapIndexed { index, path ->
                    Page(index = index, imageUrl = "${data.baseUrl}/$path")
                }))
            }
        }
        return result.copy(access = access)
    }
}
