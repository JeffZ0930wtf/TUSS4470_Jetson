/* Builds a fixed acquisition CAPTURE_DATA frame as stable segments. CRC is computed
 * over those same segments before transmission; samples are never copied. */
#include "usac_capture_stream.h"

#include "usac_sha256.h"

#define USAC_PROTOCOL_VERSION 1u
#define USAC_MESSAGE_CAPTURE_DATA 0x40u
#define USAC_FLAG_RESPONSE 0x0001u
#define USAC_FLAG_ASYNC 0x0002u
#define USAC_CAPTURE_FIXED_HEADER_LENGTH 188u
#define USAC_CAPTURE_PAYLOAD_LENGTH 4304ul

static void write_u16_le(uint8_t *target, uint16_t value)
{
    target[0] = (uint8_t)value;
    target[1] = (uint8_t)(value >> 8);
}

static void write_u32_le(uint8_t *target, uint32_t value)
{
    target[0] = (uint8_t)value;
    target[1] = (uint8_t)(value >> 8);
    target[2] = (uint8_t)(value >> 16);
    target[3] = (uint8_t)(value >> 24);
}

static void copy_bytes(uint8_t *target, const uint8_t *source, uint8_t length)
{
    uint8_t index;
    for (index = 0u; index < length; ++index) {
        target[index] = source[index];
    }
}

uint32_t usac_crc32_begin(void)
{
    return 0xFFFFFFFFul;
}

uint32_t usac_crc32_update(uint32_t crc, const uint8_t *data, uint16_t length)
{
    uint16_t index;
    uint8_t bit;

    for (index = 0u; index < length; ++index) {
        crc ^= data[index];
        for (bit = 0u; bit < 8u; ++bit) {
            crc = ((crc & 1u) != 0u) ?
                ((crc >> 1) ^ 0xEDB88320ul) : (crc >> 1);
        }
    }
    return crc;
}

uint32_t usac_crc32_finish(uint32_t crc)
{
    return crc ^ 0xFFFFFFFFul;
}

static void build_capture_id(
    const usac_capture_descriptor_t *descriptor,
    uint8_t capture_id[16])
{
    uint8_t material[36];
    uint8_t digest[32];

    copy_bytes(&material[0], descriptor->boot_id, 16u);
    copy_bytes(&material[16], descriptor->request_id, 16u);
    write_u32_le(&material[32], descriptor->capture_sequence);
    usac_sha256(material, (uint16_t)sizeof(material), digest);
    copy_bytes(capture_id, digest, 16u);
}

static void build_metadata(
    usac_capture_stream_t *stream,
    const usac_capture_descriptor_t *descriptor)
{
    uint8_t capture_id[16];
    uint8_t index;
    uint16_t offset = 0u;

    build_capture_id(descriptor, capture_id);
    write_u16_le(&stream->metadata[offset], 1u); offset += 2u;
    write_u16_le(&stream->metadata[offset], USAC_CAPTURE_FIXED_HEADER_LENGTH); offset += 2u;
    copy_bytes(&stream->metadata[offset], descriptor->request_id, 16u); offset += 16u;
    copy_bytes(&stream->metadata[offset], descriptor->schedule_id, 16u); offset += 16u;
    copy_bytes(&stream->metadata[offset], capture_id, 16u); offset += 16u;
    copy_bytes(&stream->metadata[offset], descriptor->boot_id, 16u); offset += 16u;
    copy_bytes(&stream->metadata[offset], descriptor->device_id, 16u); offset += 16u;
    copy_bytes(&stream->metadata[offset], descriptor->profile_sha256, 32u); offset += 32u;
    write_u32_le(&stream->metadata[offset], descriptor->device_config_crc32); offset += 4u;
    write_u32_le(&stream->metadata[offset], descriptor->capture_sequence); offset += 4u;
    write_u16_le(&stream->metadata[offset], descriptor->sample_interval_ticks); offset += 2u;
    write_u16_le(&stream->metadata[offset], descriptor->burst_period_ticks); offset += 2u;
    write_u16_le(&stream->metadata[offset], USAC_CAPTURE_SAMPLE_COUNT); offset += 2u;
    write_u16_le(&stream->metadata[offset], descriptor->pretrigger_count); offset += 2u;
    stream->metadata[offset++] = 12u;
    stream->metadata[offset++] = 1u;
    write_u16_le(&stream->metadata[offset], 3300u); offset += 2u;
    write_u32_le(&stream->metadata[offset], 24000000ul); offset += 4u;
    write_u32_le(&stream->metadata[offset], 0u); offset += 4u;
    for (index = 0u; index < 8u; ++index) stream->metadata[offset++] = 0u;
    write_u32_le(
        &stream->metadata[offset],
        (uint32_t)descriptor->pretrigger_count * descriptor->sample_interval_ticks);
    offset += 4u;
    write_u32_le(
        &stream->metadata[offset],
        (uint32_t)(0ul - ((uint32_t)descriptor->pretrigger_count *
                          descriptor->sample_interval_ticks)));
    offset += 4u;
    write_u32_le(&stream->metadata[offset], 1000u); offset += 4u;
    write_u32_le(&stream->metadata[offset], 0u); offset += 4u;
    write_u32_le(&stream->metadata[offset], 0u); offset += 4u;
    write_u32_le(&stream->metadata[offset], descriptor->quality_flags); offset += 4u;
    stream->metadata[offset++] = descriptor->tuss_dev_stat;
    stream->metadata[offset++] = descriptor->out3_start_level;
    stream->metadata[offset++] = descriptor->out4_start_level;
    stream->metadata[offset++] = descriptor->event_count;
    stream->metadata[offset++] = TUSS4470_PROFILE_REGISTER_COUNT;
    stream->metadata[offset++] = 0u;
    stream->metadata[offset++] = 0u;
    stream->metadata[offset++] = 0u;
    write_u32_le(&stream->metadata[offset], USAC_CAPTURE_SAMPLE_COUNT * 2ul); offset += 4u;
    for (index = 0u; index < TUSS4470_PROFILE_REGISTER_COUNT; ++index) {
        stream->metadata[offset++] = descriptor->register_pairs[index].address;
        stream->metadata[offset++] = descriptor->register_pairs[index].value;
    }
    for (index = 0u; index < descriptor->event_count; ++index) {
        const usac_capture_event_t *event = &descriptor->events[index];
        stream->metadata[offset++] = event->channel;
        stream->metadata[offset++] = event->edge;
        stream->metadata[offset++] = event->capture_method;
        stream->metadata[offset++] = event->level_after;
        write_u32_le(&stream->metadata[offset], (uint32_t)event->sample_index);
        offset += 4u;
        write_u16_le(&stream->metadata[offset], event->subsample_tick);
        offset += 2u;
        write_u16_le(&stream->metadata[offset], event->uncertainty_ticks);
        offset += 2u;
        write_u32_le(&stream->metadata[offset], event->frame_offset_ticks);
        offset += 4u;
    }
    stream->metadata_length = offset;
}

void usac_capture_stream_init(
    usac_capture_stream_t *stream,
    const usac_capture_descriptor_t *descriptor,
    const uint16_t samples[USAC_CAPTURE_SAMPLE_COUNT])
{
    uint32_t crc;

    stream->frame_header[0] = 0x55u;
    stream->frame_header[1] = 0x53u;
    stream->frame_header[2] = 0x41u;
    stream->frame_header[3] = 0x43u;
    stream->frame_header[4] = USAC_PROTOCOL_VERSION;
    stream->frame_header[5] = USAC_MESSAGE_CAPTURE_DATA;
    write_u16_le(
        &stream->frame_header[6],
        (descriptor->async_capture != 0u) ? USAC_FLAG_ASYNC : USAC_FLAG_RESPONSE);
    write_u32_le(&stream->frame_header[8], descriptor->frame_sequence);
    build_metadata(stream, descriptor);
    write_u32_le(
        &stream->frame_header[12],
        (uint32_t)stream->metadata_length + (USAC_CAPTURE_SAMPLE_COUNT * 2ul));
    stream->samples = samples;

    crc = usac_crc32_begin();
    crc = usac_crc32_update(crc, &stream->frame_header[4], 12u);
    crc = usac_crc32_update(crc, stream->metadata, stream->metadata_length);
    crc = usac_crc32_update(
        crc, (const uint8_t *)samples, USAC_CAPTURE_SAMPLE_COUNT * 2u);
    write_u32_le(stream->frame_crc, usac_crc32_finish(crc));
    stream->phase = 0u;
    stream->active = 1u;
}

uint8_t usac_capture_stream_peek(
    const usac_capture_stream_t *stream,
    const uint8_t **data,
    uint16_t *length)
{
    if ((stream == 0) || (data == 0) || (length == 0) ||
        (stream->active == 0u)) {
        return 0u;
    }
    if (stream->phase == 0u) {
        *data = stream->frame_header;
        *length = 16u;
    } else if (stream->phase == 1u) {
        *data = stream->metadata;
        *length = stream->metadata_length;
    } else if (stream->phase == 2u) {
        *data = (const uint8_t *)stream->samples;
        *length = USAC_CAPTURE_SAMPLE_COUNT * 2u;
    } else if (stream->phase == 3u) {
        *data = stream->frame_crc;
        *length = 4u;
    } else {
        return 0u;
    }
    return 1u;
}

uint8_t usac_capture_stream_commit(usac_capture_stream_t *stream)
{
    if ((stream == 0) || (stream->active == 0u) || (stream->phase >= 4u)) {
        return 0u;
    }
    ++stream->phase;
    if (stream->phase == 4u) {
        stream->active = 0u;
    }
    return 1u;
}
