package org.taloschess.studio;

import static org.junit.Assert.assertEquals;

import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Ensures the native shell installed on a device is TALOS, not a template app. */
@RunWith(AndroidJUnit4.class)
public class AppIdentityInstrumentedTest {
    @Test
    public void packageNameIsTalos() {
        assertEquals("org.taloschess.studio",
                InstrumentationRegistry.getInstrumentation().getTargetContext().getPackageName());
    }
}
