"""Tests para logging estructurado y observabilidad (B12)."""

from app.shared.logging import (
    TimingCollector,
    generate_request_id,
    get_request_id,
    set_request_id,
    stage_timer,
)


class TestRequestId:
    """Tests para request_id generation y contexto."""

    def test_generate_request_id_returns_uuid_string(self):
        """generate_request_id devuelve un string UUID v4."""
        rid = generate_request_id()
        assert isinstance(rid, str)
        assert len(rid) == 36  # UUID4 string format
        assert rid.count("-") == 4

    def test_generate_request_id_is_unique(self):
        """Cada llamada genera un ID diferente."""
        ids = [generate_request_id() for _ in range(100)]
        assert len(set(ids)) == 100

    def test_request_id_context_var_default(self):
        """Si no se establece, get_request_id devuelve 'no-request-id'."""
        # Clean up any existing context
        set_request_id("no-request-id")
        assert get_request_id() == "no-request-id"

    def test_request_id_context_var_set_and_get(self):
        """set_request_id + get_request_id funciona correctamente."""
        test_id = "test-1234-abcd"
        set_request_id(test_id)
        try:
            assert get_request_id() == test_id
        finally:
            set_request_id("no-request-id")  # cleanup


class TestTimingCollector:
    """Tests para TimingCollector."""

    def test_empty_collector_total_ms(self):
        """Un collector sin stages devuelve 0 en total_ms()."""
        tc = TimingCollector()
        assert tc.total_ms() == 0.0

    def test_add_stage_records_duration(self):
        """add_stage registra correctamente duration y metadata."""
        tc = TimingCollector()
        tc.start()
        tc.add_stage("test_stage", 50.5, key="value")
        stages = tc.get_stages()
        assert len(stages) == 1
        assert stages[0].stage == "test_stage"
        assert stages[0].duration_ms == 50.5
        assert stages[0].metadata == {"key": "value"}

    def test_add_multiple_stages(self):
        """Pueden añadirse múltiples stages en orden."""
        tc = TimingCollector()
        tc.start()
        tc.add_stage("stage1", 10.0)
        tc.add_stage("stage2", 20.0)
        tc.add_stage("stage3", 30.0)
        stages = tc.get_stages()
        assert len(stages) == 3
        assert [s.stage for s in stages] == ["stage1", "stage2", "stage3"]

    def test_total_ms_after_start(self):
        """total_ms() devuelve tiempo transcurrido desde start()."""
        tc = TimingCollector()
        tc.start()
        # Sin stages, total_ms debe ser > 0 tras un pequeño delay
        import time

        time.sleep(0.01)  # 10ms
        total = tc.total_ms()
        assert total >= 10.0  # Al menos 10ms transcurrido

    def test_to_dict_format(self):
        """to_dict() devuelve estructura correcta para debug."""
        tc = TimingCollector()
        tc.start()
        tc.add_stage("pdf_classify", 12.5)
        tc.add_stage("normalize", 45.0, candidate_count=15)

        result = tc.to_dict()
        assert "total_ms" in result
        assert "stages" in result
        assert isinstance(result["stages"], list)
        # Stages mantienen order
        assert result["stages"][0]["stage"] == "pdf_classify"
        assert result["stages"][0]["duration_ms"] == 12.5
        assert result["stages"][1]["stage"] == "normalize"
        assert result["stages"][1]["candidate_count"] == 15


class TestStageTimer:
    """Tests para stage_timer context manager."""

    def test_stage_timer_records_duration(self):
        """stage_timer registra el tiempo entre __enter__ y __exit__."""
        tc = TimingCollector()
        tc.start()

        import time

        with stage_timer(tc, "sleep_stage"):
            time.sleep(0.02)  # 20ms

        stages = tc.get_stages()
        assert len(stages) == 1
        assert stages[0].stage == "sleep_stage"
        assert stages[0].duration_ms >= 15.0  # Al menos 15ms

    def test_stage_timer_with_metadata(self):
        """stage_timer soporta metadata adicional."""
        tc = TimingCollector()
        tc.start()

        with stage_timer(tc, "ocr", engine="paddle", dpi=150):
            pass

        stages = tc.get_stages()
        assert stages[0].metadata == {"engine": "paddle", "dpi": 150}

    def test_stage_timer_nested(self):
        """Pueden anidarse múltiples stage_timer.

        Los stages se registran en orden de completion: inner (más corto)
        termina antes que outer, por lo que aparece primero en la lista.
        """
        tc = TimingCollector()
        tc.start()

        import time

        with stage_timer(tc, "outer"):
            time.sleep(0.01)
            with stage_timer(tc, "inner"):
                time.sleep(0.01)

        stages = tc.get_stages()
        assert len(stages) == 2
        # Inner completa antes (10ms) que outer (20ms) así que aparece primero
        assert stages[0].stage == "inner"
        assert stages[1].stage == "outer"
        # Inner debe ser más corto que outer
        assert stages[0].duration_ms < stages[1].duration_ms


class TestDebugInfo:
    """Tests para build_debug_info."""

    def test_build_debug_info_minimal(self):
        """build_debug_info con parámetros mínimos."""
        from app.shared.debug_info import build_debug_info

        result = build_debug_info(
            request_id="req-123",
            stage="digital_pipeline",
            timings={"total_ms": 150.0, "stages": []},
        )
        assert result["request_id"] == "req-123"
        assert result["stage"] == "digital_pipeline"
        assert result["timings"]["total_ms"] == 150.0

    def test_build_debug_info_all_params(self):
        """build_debug_info con todos los parámetros opcionales."""
        from app.shared.debug_info import build_debug_info

        result = build_debug_info(
            request_id="req-456",
            stage="ocr_pipeline",
            timings={"total_ms": 500.0, "stages": []},
            pdf_kind="scanned",
            pipeline="ocr",
            engine="paddle",
            candidate_count=42,
            resolved_fields=["invoice_data.number", "totals.gross_amount"],
            warnings_count=2,
            errors_count=0,
            vlm_used=False,
            extra_key="extra_value",
        )
        assert result["pdf_kind"] == "scanned"
        assert result["pipeline"] == "ocr"
        assert result["engine"] == "paddle"
        assert result["candidate_count"] == 42
        assert result["resolved_fields"] == [
            "invoice_data.number",
            "totals.gross_amount",
        ]
        assert result["warnings_count"] == 2
        assert result["extra_key"] == "extra_value"
        assert "vlm_used" not in result  # False no se incluye

    def test_debug_info_no_sensitive_data(self):
        """Debug info NO debe incluir contenido de facturas."""
        from app.shared.debug_info import build_debug_info

        result = build_debug_info(
            request_id="req-789",
            stage="digital_pipeline",
            timings={"total_ms": 100.0, "stages": []},
        )
        # Solo metadatos operativos — nunca datos de la factura
        assert "invoice" not in result
        assert "supplier" not in result
        assert "customer" not in result
        assert "tax_id" not in result
        assert "legal_name" not in result
        assert "amount" not in result
        # Lo que SÍ debe tener
        assert "request_id" in result
        assert "stage" in result
        assert "timings" in result


class TestDebugVisualPending:
    """Tests para el flag DEBUG_VISUAL_PENDING."""

    def test_debug_visual_pending_is_true(self):
        """DEBUG_VISUAL_PENDING indica que debug visual es pendiente."""
        from app.shared.debug_info import DEBUG_VISUAL_PENDING

        assert DEBUG_VISUAL_PENDING is True