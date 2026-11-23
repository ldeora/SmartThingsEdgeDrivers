package main

import (
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"
	"charm.land/huh/v2"
)

// Run the commands returned by the Huh form in process, without starting
// a terminal or invoking any of the demo's (deliberately inert) main flow.
// Huh schedules DescriptionFunc refreshes as commands, so inspecting s.preview()
// alone would NOT catch stale values on its rendered Review page.
func deliverFormMessage(t *testing.T, form *huh.Form, msg tea.Msg) {
	t.Helper()
	queue := []tea.Msg{msg}
	for steps := 0; len(queue) > 0; steps++ {
		if steps >= 300 {
			t.Fatal("Huh form did not settle within 300 messages")
		}
		current := queue[0]
		queue = queue[1:]
		if batch, ok := current.(tea.BatchMsg); ok {
			for _, cmd := range batch {
				if cmd != nil {
					queue = append(queue, cmd())
				}
			}
			continue
		}
		_, cmd := form.Update(current)
		if cmd != nil {
			queue = append(queue, cmd())
		}
	}
}

func TestReviewPageRefreshesRenderedPlan(t *testing.T) {
	s := selection{
		action: "install", hubChoice: "none",
		powerChoice: "keep", wolChoice: "keep",
	}
	form := interactiveForm(&s).WithWidth(120).WithHeight(45)

	// First visit. Hub/manual warning pages are hidden. The Features page
	// has two fields, hence four NextField events reach Review.
	for i := 0; i < 4; i++ {
		deliverFormMessage(t, form, huh.NextField())
	}
	initial := form.View()
	for _, want := range []string{
		"Fresh installation", "None selected",
		"Power management: false", "Persistent Wake-on-LAN: false",
	} {
		if !strings.Contains(initial, want) {
			t.Fatalf("initial rendered Review missing %q:\n%s", want, initial)
		}
	}

	// Simulate choices changed on earlier screens. Huh must invalidate its
	// cached DescriptionFunc value and visibly update the active Review page.
	s.action = "upgrade"
	s.hubChoice = "demo-a"
	s.powerChoice = "enabled"
	s.wolChoice = "enabled"
	deliverFormMessage(t, form, tea.WindowSizeMsg{Width: 120, Height: 45})
	updated := form.View()
	for _, want := range []string{
		"Existing installation upgrade", "Demo hub A",
		"Power management: true", "Persistent Wake-on-LAN: true",
	} {
		if !strings.Contains(updated, want) {
			t.Fatalf("updated rendered Review missing %q:\n%s", want, updated)
		}
	}
	for _, stale := range []string{"Fresh installation", "None selected"} {
		if strings.Contains(updated, stale) {
			t.Fatalf("updated rendered Review contains stale %q:\n%s", stale, updated)
		}
	}

	// Exercise the cached path in the opposite direction as well: returning
	// to the original selections must not keep the upgrade plan on screen.
	s.action = "install"
	s.hubChoice = "none"
	s.powerChoice = "keep"
	s.wolChoice = "keep"
	deliverFormMessage(t, form, tea.WindowSizeMsg{Width: 120, Height: 45})
	backToOriginal := form.View()
	if !strings.Contains(backToOriginal, "Fresh installation") ||
		strings.Contains(backToOriginal, "Existing installation upgrade") {
		t.Fatalf("restored rendered Review did not update:\n%s", backToOriginal)
	}
}
